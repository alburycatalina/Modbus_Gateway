"""
Modbus / TagoTIP gateway: one thread per device in pollees.csv.

Each thread polls Modbus/TCP (ADAM or similar), pushes readings to Tago.io via TagoTIP
over TCP, and persists last values for delta calculations.

Constraints handled explicitly:
- TagoTIP: ~5s application idle limit and ~10s connection TTL on Free/Starter (see Tago docs).
- Modbus/TCP: many slaves close idle TCP after roughly one poll interval; refresh client after waits.
"""

import csv
import json
import logging
import os
import random
import socket
import threading
import time

from dotenv import load_dotenv
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException

# ---------------------------------------------------------------------------
# Configuration (env overrides where noted)
# ---------------------------------------------------------------------------

load_dotenv()
AUTH_HASH = os.getenv("AUTH_HASH")
if not AUTH_HASH:
    raise RuntimeError("Missing AUTH_HASH in environment/.env")

ADAM_PORT = 502
POLL_INTERVAL = 60


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return float(raw)


# Seconds between uplink frames during Tago idle waits (must stay below server ~5s idle cap).
TAGO_KEEPALIVE_INTERVAL = _float_env("TAGO_KEEPALIVE_INTERVAL", 4.0)
# New TCP session before this many seconds since last Tago connect (stay under server TTL).
TAGO_TTL_RECONNECT_BEFORE = _float_env("TAGO_TTL_RECONNECT_BEFORE", 9.0)

# Optional periodic full Tago reconnect for hygiene (independent of TTL churn).
RECONNECT_INTERVAL_SEC = int(os.getenv("TAGO_SCHEDULED_RECONNECT_SEC", "3600"))

TAGO_HOST = "tcp.tip.us-e1.tago.io"
TAGO_PORT = 5693
DEVICES_FILE = "pollees.csv"
LOG_FILE = "poller.log"
LAST_VALUES_FILE = "last_values.json"

POLL_REGISTER_ADDRESS = 0x0018
POLL_REGISTER_COUNT = 1
TAGO_VARIABLE_NAME = "countfreq"

RECONNECT_BACKOFF_BASE = 1
RECONNECT_BACKOFF_CAP = 30

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_file_handler = logging.FileHandler(LOG_FILE)
_file_handler.setFormatter(_formatter)
log.addHandler(_file_handler)

# Protects shared JSON state written from multiple device threads.
state_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

# ADAM 6051 counters must have  
# countfreq = (value of 40002) x 65536 + (value of 40001)

def decode_register_value(registers, encoding):
    """Combine raw Modbus register words into a single value per encoding."""
    if encoding == "uint32_lohi":
        # Low word first: registers[0]=low, registers[1]=high
        return registers[0] + registers[1] * 65536
    if encoding == "uint32_hilo":
        # High word first: registers[0]=high, registers[1]=low
        return registers[1] + registers[0] * 65536
    # Default: single uint16
    return registers[0]

# ---------------------------------------------------------------------------
# Persisted state (deltas across restarts)
# ---------------------------------------------------------------------------


def load_last_values_state(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        log.warning("State file %s is not a JSON object. Starting empty.", filepath)
        return {}
    except Exception as e:
        log.warning("Failed to load state file %s (%s). Starting empty.", filepath, e)
        return {}


def save_last_values_state(filepath, state):
    temp_path = f"{filepath}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(temp_path, filepath)


def compute_delta(current_value, previous_value, rollover_bits):
    """Difference since last sample; optional counter rollover using rollover_bits width."""
    if previous_value is None:
        return 0
    delta = current_value - previous_value
    if delta >= 0:
        return delta
    if rollover_bits and rollover_bits > 0:
        max_value = (1 << rollover_bits) - 1
        if previous_value <= max_value and current_value <= max_value:
            return (max_value - previous_value) + current_value + 1
    return 0


# ---------------------------------------------------------------------------
# Device list (CSV)
# ---------------------------------------------------------------------------


def load_devices(filepath):
    """Build device dicts with register_points[] used by the poll loop."""

    def parse_int(value, default):
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        return int(text, 0)

    def parse_register_points(row):
        # registers=variable:address[:count[:rollover_bits]];...
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
            if len(pieces) not in (2, 3, 4, 5):
                raise ValueError(
                    f"Invalid registers entry '{part}'. "
                    "Expected variable:address[:count[:rollover_bits[:encoding]]]"
                )
            variable = pieces[0]
            address = int(pieces[1], 0)
            count = int(pieces[2], 0) if len(pieces) >= 3 else 1
            rollover_bits = int(pieces[3], 0) if len(pieces) >= 4 else 16 * max(1, count)
            encoding = pieces[4] if len(pieces) == 5 else ("uint32_lohi" if count == 2 else "uint16")
            points.append({
                "variable": variable,
                "address": address,
                "count": count,
                "rollover_bits": rollover_bits,
                "encoding": encoding,
            })
        if not points:
            raise ValueError("registers field was provided but no valid entries were found")
        return points

    devices = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            devices.append({
                "name": row["name"],
                "ip": row["ip"],
                "serial": row["serial"],
                "register_points": parse_register_points(row),
            })
    log.info("Loaded %d device(s) from %s", len(devices), filepath)
    return devices


# ---------------------------------------------------------------------------
# Modbus/TCP (server)
# ---------------------------------------------------------------------------


def connect_modbus(ip, name, *, log_success=True):
    """Block until Modbus/TCP connects."""
    while True:
        client = ModbusTcpClient(host=ip, port=ADAM_PORT)
        if client.connect():
            msg = f"[{name}] Connected to ADAM at {ip}"
            log.info(msg) if log_success else log.debug(msg)
            return client
        log.warning("[%s] Failed to connect to ADAM at %s — retrying in 5s", name, ip)
        time.sleep(5)


def refresh_modbus_after_idle(device):
    """Close and reopen Modbus client after POLL_INTERVAL with no Modbus traffic."""
    name = device["name"]
    ip = device["ip"]
    try:
        device["modbus"].close()
    except Exception:
        pass
    device["modbus"] = connect_modbus(ip, name, log_success=False)
    log.debug("[%s] Modbus TCP session reopened after idle window", name)


# ---------------------------------------------------------------------------
# TagoTIP (TCP line protocol)
# ---------------------------------------------------------------------------


def connect_tago(name="", *, log_success=True):
    """Block until Tago TCP connects."""
    attempt = 0
    while True:
        attempt += 1
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for opt_name, opt_value in (
                ("TCP_KEEPIDLE", 30),
                ("TCP_KEEPINTVL", 5),
                ("TCP_KEEPCNT", 3),
            ):
                opt = getattr(socket, opt_name, None)
                if opt is None:
                    continue
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, opt, opt_value)
                except OSError as e:
                    log.warning("[%s] Keepalive option %s unsupported (%s)", name, opt_name, e)
            sock.settimeout(10)
            sock.connect((TAGO_HOST, TAGO_PORT))
            msg = f"[{name}] Connected to TagoIO (attempt {attempt})"
            log.info(msg) if log_success else log.debug(msg)
            return sock
        except Exception as e:
            wait = min(30, 5 * attempt)
            log.warning("[%s] TagoIO connect failed (%s) — retrying in %ss", name, e, wait)
            time.sleep(wait)


def send_frame(sock, frame, ack_timeout=8):
    """Send one line-terminated frame; return ACK text or empty string on recv timeout."""
    sock.sendall(frame.encode())
    previous_timeout = sock.gettimeout()
    try:
        sock.settimeout(ack_timeout)
        return sock.recv(1024).decode().strip()
    except socket.timeout:
        return ""
    finally:
        sock.settimeout(previous_timeout)


def reconnect_tago(device, *, log_connect=True):
    """Replace Tago socket; send post-connect PING to satisfy application idle timer."""
    name = device["name"]
    old = device.get("tago_socket")
    if old is not None:
        try:
            old.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            old.close()
        except OSError:
            pass
    device["tago_socket"] = connect_tago(name, log_success=log_connect)
    device["tago_connect_time"] = time.time()
    ping_frame = f"PING|{AUTH_HASH}|{device['serial']}\n"
    try:
        ack = send_frame(device["tago_socket"], ping_frame, ack_timeout=6)
        if ack and "ERR" in ack:
            log.warning("[%s] Post-connect PING error (%s)", name, ack)
    except OSError as e:
        log.warning("[%s] Post-connect PING failed (%s)", name, e)
    device["last_ping"] = time.time()


def sleep_reconnect_backoff(device):
    """Exponential backoff with jitter after Tago failures."""
    errors = max(1, device.get("consecutive_errors", 1))
    raw_delay = min(RECONNECT_BACKOFF_CAP, RECONNECT_BACKOFF_BASE * (2 ** (errors - 1)))
    delay = random.uniform(raw_delay * 0.5, raw_delay)
    log.info(
        "[%s] Reconnect backoff: sleeping %.1fs (errors=%s, base=%ss)",
        device["name"], delay, errors, raw_delay,
    )
    time.sleep(delay)


def maintain_tago_socket_during_idle(device, total_sleep_seconds):
    """
    Sleep total_sleep_seconds while keeping TagoTIP alive:
    - PING often enough to beat ~5s idle limit.
    - New TCP session before ~10s connection TTL (Free/Starter).
    """
    deadline = time.time() + total_sleep_seconds
    serial = device["serial"]
    name = device["name"]

    while time.time() < deadline:
        now = time.time()
        try:
            if now - device["tago_connect_time"] >= TAGO_TTL_RECONNECT_BEFORE:
                log.debug("[%s] Proactive Tago reconnect (connection TTL)", name)
                reconnect_tago(device, log_connect=False)
                continue

            if now - device["last_ping"] >= TAGO_KEEPALIVE_INTERVAL:
                ping_frame = f"PING|{AUTH_HASH}|{serial}\n"
                ack = send_frame(device["tago_socket"], ping_frame, ack_timeout=6)
                log.debug("[%s] Idle PING: %s", name, ack or "<no-ack>")
                device["last_ping"] = time.time()
                if ack and "ERR" in ack:
                    log.warning("[%s] Idle PING error (%s) — reconnecting...", name, ack)
                    reconnect_tago(device, log_connect=False)
                    continue

        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            log.warning("[%s] Tago idle keepalive failed (%s) — reconnecting...", name, e)
            reconnect_tago(device, log_connect=False)
            continue

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(1.0, remaining))

    margin = 1.0
    if time.time() - device["tago_connect_time"] >= TAGO_TTL_RECONNECT_BEFORE - margin:
        log.debug("[%s] Refreshing Tago session before uplink (near TTL)", name)
        reconnect_tago(device, log_connect=False)






# ---------------------------------------------------------------------------
# Per-device thread
# ---------------------------------------------------------------------------


def run_device(device):
    """
    Loop forever: (optional Modbus refresh) → Tago housekeeping → read registers → PUSH →
    sleep POLL_INTERVAL on Tago-only maintenance → repeat.

    first_modbus_poll skips Modbus refresh on the very first iteration (fresh connect above).
    """
    name = device["name"]
    serial = device["serial"]
    register_points = device["register_points"]

    device["modbus"] = connect_modbus(device["ip"], name)
    device["tago_socket"] = None
    reconnect_tago(device, log_connect=True)
    device["consecutive_errors"] = 0
    device["cooldown_until"] = 0
    device["last_values"] = {}
    device["next_scheduled_tago_reconnect"] = time.time() + RECONNECT_INTERVAL_SEC

    with state_lock:
        serial_state = state.get(serial, {})
        if isinstance(serial_state, dict):
            for point in register_points:
                value = serial_state.get(point["variable"])
                if isinstance(value, int):
                    device["last_values"][point["variable"]] = value

    first_modbus_poll = True

    while True:
        if time.time() < device["cooldown_until"]:
            rem = device["cooldown_until"] - time.time()
            log.info("[%s] Cooldown — %.0fs remaining", name, rem)
            time.sleep(5)
            continue

        if not first_modbus_poll:
            refresh_modbus_after_idle(device)

        tago_socket = device["tago_socket"]
        client = device["modbus"]

        try:
            # Scheduled reconnect uses its own deadline (not last_reconnect — that updates on every TTL reconnect).
            if time.time() >= device["next_scheduled_tago_reconnect"]:
                log.info("[%s] Scheduled Tago reconnect (%ss interval)", name, RECONNECT_INTERVAL_SEC)
                reconnect_tago(device, log_connect=True)
                tago_socket = device["tago_socket"]
                device["next_scheduled_tago_reconnect"] = time.time() + RECONNECT_INTERVAL_SEC

            if time.time() - device["tago_connect_time"] >= TAGO_TTL_RECONNECT_BEFORE:
                log.debug("[%s] Proactive Tago reconnect before uplink (TTL)", name)
                reconnect_tago(device, log_connect=False)
                tago_socket = device["tago_socket"]

            if time.time() - device["last_ping"] >= TAGO_KEEPALIVE_INTERVAL:
                ping_frame = f"PING|{AUTH_HASH}|{serial}\n"
                try:
                    ack = send_frame(tago_socket, ping_frame, ack_timeout=6)
                except (ConnectionResetError, BrokenPipeError, OSError) as e:
                    raise ConnectionAbortedError(f"Tago PING failed: {e}") from e
                log.info("[%s] PING: %s", name, ack or "<no-ack>")
                device["last_ping"] = time.time()
                if ack and "ERR" in ack:
                    log.warning("[%s] PING error (%s) — reconnecting...", name, ack)
                    reconnect_tago(device, log_connect=True)
                    tago_socket = device["tago_socket"]
                    time.sleep(2)
                    continue

            for point in register_points:
                try:
                    reg_result = client.read_holding_registers(
                        address=point["address"],
                        count=point["count"],
                    )
                except OSError as e:
                    log.warning(
                        "[%s] Modbus TCP error (%s: %s) — reconnecting Modbus...",
                        name, type(e).__name__, e,
                    )
                    client.close()
                    device["modbus"] = connect_modbus(device["ip"], name)
                    client = device["modbus"]
                    break

                if reg_result is None or reg_result.isError():
                    log.warning(
                        "[%s] Modbus read failed for %s (address=%s, count=%s) — reconnecting Modbus...",
                        name, point["variable"], point["address"], point["count"],
                    )
                    client.close()
                    device["modbus"] = connect_modbus(device["ip"], name)
                    client = device["modbus"]
                    break

                value = decode_register_value(reg_result.registers, point.get("encoding", "uint16"))
                variable_name = point["variable"]
                previous_value = device["last_values"].get(variable_name)
                delta = compute_delta(value, previous_value, point["rollover_bits"])

                frame = f"PUSH|{AUTH_HASH}|{serial}|[{variable_name}:={value}]\n"
                try:
                    ack = send_frame(tago_socket, frame, ack_timeout=8)
                except (ConnectionResetError, BrokenPipeError, OSError) as e:
                    raise ConnectionAbortedError(f"Tago PUSH failed: {e}") from e
                log.info("[%s] Sent: %s", name, frame.strip())
                log.info("[%s] ACK:  %s", name, ack or "<no-ack>")
                if ack and "ERR" in ack:
                    raise ConnectionAbortedError(f"TagoIO returned error ACK: {ack}")

                delta_frame = f"PUSH|{AUTH_HASH}|{serial}|[{variable_name}_delta:={delta}]\n"
                try:
                    delta_ack = send_frame(tago_socket, delta_frame, ack_timeout=8)
                except (ConnectionResetError, BrokenPipeError, OSError) as e:
                    raise ConnectionAbortedError(f"Tago PUSH (delta) failed: {e}") from e
                log.info("[%s] Sent: %s", name, delta_frame.strip())
                log.info("[%s] ACK:  %s", name, delta_ack or "<no-ack>")
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
                "[%s] TagoIO connection lost (%s: %s) — error #%s",
                name, type(e).__name__, e, device["consecutive_errors"],
            )
            if device["consecutive_errors"] >= 5:
                device["cooldown_until"] = time.time() + 60
                device["consecutive_errors"] = 0
                log.warning("[%s] Too many errors — cooling down for 60s", name)
            else:
                sleep_reconnect_backoff(device)
                reconnect_tago(device, log_connect=True)
                tago_socket = device["tago_socket"]

        except (ModbusException, ConnectionException) as e:
            log.error("[%s] Modbus error (%s) — reconnecting...", name, e)
            try:
                client.close()
            except Exception:
                pass
            device["modbus"] = connect_modbus(device["ip"], name)

        except Exception as e:
            log.error("[%s] Unexpected error (%s)", name, e)
            device["consecutive_errors"] += 1
            sleep_reconnect_backoff(device)
            reconnect_tago(device, log_connect=True)

        maintain_tago_socket_during_idle(device, POLL_INTERVAL)
        first_modbus_poll = False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

devices = load_devices(DEVICES_FILE)
state = load_last_values_state(LAST_VALUES_FILE)

for _dev in devices:
    threading.Thread(target=run_device, args=(_dev,), daemon=True).start()
    log.info("Started thread for [%s]", _dev["name"])

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    log.info("Stopping...")