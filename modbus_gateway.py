import time
import socket
import csv
import threading
import random
import json
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException, ConnectionException
from dotenv import load_dotenv
import os
import logging

# Set variables
load_dotenv()
AUTH_HASH = os.getenv("AUTH_HASH")
if not AUTH_HASH: # if AUTH_HASH is not set, raise an error
    raise RuntimeError("Missing AUTH_HASH in environment/.env")
ADAM_PORT = 502
POLL_INTERVAL = 60
PING_INTERVAL = 20
RECONNECT_INTERVAL = 3600 # attempt to reconnect every hour
TAGO_HOST = "tcp.tip.us-e1.tago.io" # TagoIO host
TAGO_PORT = 5693 # TagoIO port1
DEVICES_FILE = "pollees.csv" # list of devices to poll
LOG_FILE = "poller.log" # lof of warnings and frames sent/received
LAST_VALUES_FILE = "last_values.json"
POLL_REGISTER_ADDRESS = 0x0018 # default register if not stated in pollees.csv 
POLL_REGISTER_COUNT = 1
TAGO_VARIABLE_NAME = "countfreq"
RECONNECT_BACKOFF_BASE = 1
RECONNECT_BACKOFF_CAP = 30


# Create file that logs output
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)

log.addHandler(file_handler)

state_lock = threading.Lock()

# Load last value from JSON file for calculating deltas
def load_last_values_state(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        log.warning(f"State file {filepath} is not a JSON object. Starting with empty state.")
        return {}
    except Exception as e:
        log.warning(f"Failed to load state file {filepath} ({e}). Starting with empty state.")
        return {}

# Save last value in count frequency to a json file
def save_last_values_state(filepath, state):
    temp_path = f"{filepath}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(temp_path, filepath)

# Compute the delta between the current and previous value from value in JSON 
def compute_delta(current_value, previous_value, rollover_bits):
    if previous_value is None:
        return 0

    delta = current_value - previous_value
    if delta >= 0:
        return delta

    if rollover_bits and rollover_bits > 0:
        max_value = (1 << rollover_bits) - 1
        if previous_value <= max_value and current_value <= max_value:
            return (max_value - previous_value) + current_value + 1

    # If negative and no valid rollover configuration, assume reset/noisy reading.
    return 0



def load_devices(filepath):
    def parse_int(value, default):
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        return int(text, 0)

    def parse_register_points(row):
        # Format:
        # registers=variable:address[:count[:rollover_bits]];...
        # Examples:
        # countfreq:0x18
        # countfreq:0x18:1:16;total_count:0x20:2:32
        text = (row.get("registers") or "").strip()
        if not text:
            default_count = parse_int(row.get("register_count"), POLL_REGISTER_COUNT)
            return [{
                "variable": (row.get("variable_name") or TAGO_VARIABLE_NAME).strip(),
                "address": parse_int(row.get("register_address"), POLL_REGISTER_ADDRESS),
                "count": default_count,
                "rollover_bits": 16 * max(1, default_count),
            }]

        points = []
        for raw_part in text.split(";"):
            part = raw_part.strip()
            if not part:
                continue
            pieces = [p.strip() for p in part.split(":")]
            if len(pieces) not in (2, 3, 4):
                raise ValueError(
                    f"Invalid registers entry '{part}'. "
                    "Expected variable:address[:count[:rollover_bits]]"
                )
            variable = pieces[0]
            address = int(pieces[1], 0)
            count = int(pieces[2], 0) if len(pieces) == 3 else 1
            rollover_bits = int(pieces[3], 0) if len(pieces) == 4 else 16 * max(1, count)
            points.append({
                "variable": variable,
                "address": address,
                "count": count,
                "rollover_bits": rollover_bits,
            })

        if not points:
            raise ValueError("registers field was provided but no valid entries were found")
        return points

    devices = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            register_points = parse_register_points(row)
            devices.append({
                "name":   row["name"],
                "ip":     row["ip"],
                "serial": row["serial"],
                # Optional per-device overrides in pollees.csv:
                # register_address, register_count, variable_name
                "register_address": parse_int(row.get("register_address"), POLL_REGISTER_ADDRESS),
                "register_count": parse_int(row.get("register_count"), POLL_REGISTER_COUNT),
                "variable_name": (row.get("variable_name") or TAGO_VARIABLE_NAME).strip(),
                "register_points": register_points,
            })
    log.info(f"Loaded {len(devices)} device(s) from {filepath}")
    return devices

def connect_modbus(ip, name):
    while True:
        client = ModbusTcpClient(host=ip, port=ADAM_PORT)
        if client.connect():
            log.info(f"[{name}] Connected to ADAM at {ip}")
            return client
        log.warning(f"[{name}] Failed to connect to ADAM at {ip} — retrying in 5s")
        time.sleep(5)

def connect_tago(name=""):
    attempt = 0
    while True:
        attempt += 1
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # Socket keepalive options
            for opt_name, opt_value in (
                ("TCP_KEEPIDLE", 30), # idle time (seconds) before sending keepalive probe
                ("TCP_KEEPINTVL", 5), # interval (seconds) between keepalive probes
                ("TCP_KEEPCNT", 3), # number of keepalive probes to send before considering the connection dead
            ):
                opt = getattr(socket, opt_name, None)
                if opt is None:
                    continue
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, opt, opt_value)
                except OSError as e:
                    log.warning(f"[{name}] Keepalive option {opt_name} unsupported ({e})")
            sock.settimeout(10)
            sock.connect((TAGO_HOST, TAGO_PORT))
            log.info(f"[{name}] Connected to TagoIO (attempt {attempt})")
            return sock
        except Exception as e:
            wait = min(30, 5 * attempt)
            log.warning(f"[{name}] TagoIO connect failed ({e}) — retrying in {wait}s")
            time.sleep(wait)

def send_frame(sock, frame, ack_timeout=8):
    sock.sendall(frame.encode())
    previous_timeout = sock.gettimeout()
    try:
        sock.settimeout(ack_timeout)
        return sock.recv(1024).decode().strip()
    except socket.timeout:
        # Missing ACK is common on busy links; treat as soft failure.
        return ""
    finally:
        sock.settimeout(previous_timeout)

def reconnect_tago(device):
    name = device["name"]
    try:
        device["tago_socket"].close()
    except Exception:
        pass
    device["tago_socket"] = connect_tago(name)
    device["last_reconnect"] = time.time()
    device["last_ping"] = time.time()

# stops all devices from polling for a random amount of time to prevent overwhelming the server
def sleep_reconnect_backoff(device):
    errors = max(1, device.get("consecutive_errors", 1))
    raw_delay = min(RECONNECT_BACKOFF_CAP, RECONNECT_BACKOFF_BASE * (2 ** (errors - 1)))
    delay = random.uniform(raw_delay * 0.5, raw_delay) #jitter the delay to prevent all devices from reconnecting at the same time
    log.info(
        f"[{device['name']}] Reconnect backoff: sleeping {delay:.1f}s "
        f"(errors={errors}, base={raw_delay}s)"
    )
    time.sleep(delay)

def run_device(device):
    """Main polling loop for a single device — runs in its own thread."""
    name   = device["name"]
    serial = device["serial"]
    register_points = device["register_points"]

    device["modbus"]           = connect_modbus(device["ip"], name)
    device["tago_socket"]      = connect_tago(name)
    device["last_ping"]        = time.time()
    device["last_reconnect"]   = time.time()
    device["consecutive_errors"] = 0
    device["cooldown_until"]   = 0
    device["last_values"] = {}

    with state_lock:
        serial_state = state.get(serial, {})
        if isinstance(serial_state, dict):
            for point in register_points:
                value = serial_state.get(point["variable"])
                if isinstance(value, int):
                    device["last_values"][point["variable"]] = value

    while True:
        # Cooldown check
        if time.time() < device["cooldown_until"]:
            remaining = device["cooldown_until"] - time.time()
            log.info(f"[{name}] Cooldown — {remaining:.0f}s remaining")
            time.sleep(5)
            continue

        tago_socket = device["tago_socket"]
        client      = device["modbus"]

        try:
            # Proactive reconnect every 12 hours
            if time.time() - device["last_reconnect"] >= RECONNECT_INTERVAL: # if last reconnect was more than an hour ago, reconnect
                log.info(f"[{name}] Scheduled reconnect...")
                reconnect_tago(device)
                tago_socket = device["tago_socket"]

            # PING if due
            if time.time() - device["last_ping"] >= PING_INTERVAL:
                ping_frame = f"PING|{AUTH_HASH}|{serial}\n"
                ack = send_frame(tago_socket, ping_frame, ack_timeout=6)
                log.info(f"[{name}] PING: {ack or '<no-ack>'}")
                device["last_ping"] = time.time()

                if ack and "ERR" in ack:
                    log.warning(f"[{name}] PING error ({ack}) — reconnecting...")
                    reconnect_tago(device)
                    tago_socket = device["tago_socket"]
                    continue

            for point in register_points:
                reg_result = client.read_holding_registers(
                    address=point["address"],
                    count=point["count"],
                )
                if reg_result is None or reg_result.isError():
                    log.warning(
                        f"[{name}] Modbus read failed for {point['variable']} "
                        f"(address={point['address']}, count={point['count']}) "
                        "— reconnecting Modbus..."
                    )
                    client.close()
                    device["modbus"] = connect_modbus(device["ip"], name)
                    break

                # Sends the first register from each read. If count > 1, combine words as needed per metric.
                value = reg_result.registers[0]
                variable_name = point["variable"]
                previous_value = device["last_values"].get(variable_name)
                delta = compute_delta(value, previous_value, point["rollover_bits"])

                frame = f"PUSH|{AUTH_HASH}|{serial}|[{variable_name}:={value}]\n"
                ack = send_frame(tago_socket, frame, ack_timeout=8)
                log.info(f"[{name}] Sent: {frame.strip()}")
                log.info(f"[{name}] ACK:  {ack or '<no-ack>'}")
                if ack and "ERR" in ack:
                    raise ConnectionAbortedError(f"TagoIO returned error ACK: {ack}")

                delta_frame = f"PUSH|{AUTH_HASH}|{serial}|[{variable_name}_delta:={delta}]\n"
                delta_ack = send_frame(tago_socket, delta_frame, ack_timeout=8)
                log.info(f"[{name}] Sent: {delta_frame.strip()}")
                log.info(f"[{name}] ACK:  {delta_ack or '<no-ack>'}")
                if delta_ack and "ERR" in delta_ack:
                    raise ConnectionAbortedError(f"TagoIO returned error ACK: {delta_ack}")

                device["last_values"][variable_name] = value
                with state_lock:
                    state.setdefault(serial, {})[variable_name] = value
                    save_last_values_state(LAST_VALUES_FILE, state)
            else:
                device["consecutive_errors"] = 0

        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError) as e:
            device["consecutive_errors"] += 1
            log.error(
                f"[{name}] TagoIO connection lost "
                f"({type(e).__name__}: {e}) — error #{device['consecutive_errors']}"
            )

            if device["consecutive_errors"] >= 5:
                cooldown = 60
                device["cooldown_until"] = time.time() + cooldown
                device["consecutive_errors"] = 0
                log.warning(f"[{name}] Too many errors — cooling down for {cooldown}s")
            else:
                sleep_reconnect_backoff(device)
                reconnect_tago(device)
                tago_socket = device["tago_socket"]

        except (ModbusException, ConnectionException) as e:
            log.error(f"[{name}] Modbus connection lost ({e}) — reconnecting...")
            client.close()
            device["modbus"] = connect_modbus(device["ip"], name)

        except Exception as e:
            log.error(f"[{name}] Unexpected error ({e})")
            device["consecutive_errors"] += 1
            sleep_reconnect_backoff(device)
            reconnect_tago(device)

        time.sleep(POLL_INTERVAL)

# --- Main ---
devices = load_devices(DEVICES_FILE)
state = load_last_values_state(LAST_VALUES_FILE)

threads = []
for device in devices:
    t = threading.Thread(target=run_device, args=(device,), daemon=True)
    t.start()
    threads.append(t)
    log.info(f"Started thread for [{device['name']}]")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    log.info("Stopping...")