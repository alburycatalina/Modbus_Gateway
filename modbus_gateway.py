import time
import socket
import csv
import threading
from datetime import datetime
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException, ConnectionException
from dotenv import load_dotenv
import os
import logging

# Set variables
load_dotenv()
AUTH_HASH = os.getenv("AUTH_HASH")
ADAM_PORT = 502
POLL_INTERVAL = 10
PING_INTERVAL = 20
RECONNECT_INTERVAL = 3600 * 12
TAGO_HOST = "tcp.tip.us-e1.tago.io"
TAGO_PORT = 5693
DEVICES_FILE = "pollees.csv"
LOG_FILE = "poller.log"


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



def load_devices(filepath):
    devices = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            devices.append({
                "name":   row["name"],
                "ip":     row["ip"],
                "serial": row["serial"],
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
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
            sock.settimeout(10)
            sock.connect((TAGO_HOST, TAGO_PORT))
            log.info(f"[{name}] Connected to TagoIO (attempt {attempt})")
            return sock
        except Exception as e:
            wait = min(30, 5 * attempt)
            log.warning(f"[{name}] TagoIO connect failed ({e}) — retrying in {wait}s")
            time.sleep(wait)

def send_frame(sock, frame):
    sock.sendall(frame.encode())
    return sock.recv(1024).decode().strip()

def reconnect_tago(device):
    name = device["name"]
    try:
        device["tago_socket"].close()
    except Exception:
        pass
    device["tago_socket"] = connect_tago(name)
    device["last_reconnect"] = time.time()
    device["last_ping"] = time.time()
    device["consecutive_errors"] = 0

def run_device(device):
    """Main polling loop for a single device — runs in its own thread."""
    name   = device["name"]
    serial = device["serial"]

    device["modbus"]           = connect_modbus(device["ip"], name)
    device["tago_socket"]      = connect_tago(name)
    device["last_ping"]        = time.time()
    device["last_reconnect"]   = time.time()
    device["consecutive_errors"] = 0
    device["cooldown_until"]   = 0

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
            if time.time() - device["last_reconnect"] >= RECONNECT_INTERVAL:
                log.info(f"[{name}] Scheduled reconnect...")
                reconnect_tago(device)
                tago_socket = device["tago_socket"]

            # PING if due
            if time.time() - device["last_ping"] >= PING_INTERVAL:
                ping_frame = f"PING|{AUTH_HASH}|{serial}\n"
                ack = send_frame(tago_socket, ping_frame)
                log.info(f"[{name}] PING: {ack}")
                device["last_ping"] = time.time()

                if "ERR" in ack:
                    log.warning(f"[{name}] PING error ({ack}) — reconnecting...")
                    reconnect_tago(device)
                    tago_socket = device["tago_socket"]
                    continue

            # Read from ADAM
            reg_result = client.read_holding_registers(address=0x0018, count=1)
            if reg_result is None or reg_result.isError():
                log.warning(f"[{name}] Modbus read failed — reconnecting Modbus...")
                client.close()
                device["modbus"] = connect_modbus(device["ip"], name)
                continue

            # Send to TagoIO
            freq = reg_result.registers[0]
            frame = f"PUSH|{AUTH_HASH}|{serial}|[countfreq:={freq}]\n"
            ack = send_frame(tago_socket, frame)
            log.info(f"[{name}] Sent: {frame.strip()}")
            log.info(f"[{name}] ACK:  {ack}")
            device["consecutive_errors"] = 0

        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError) as e:
            device["consecutive_errors"] += 1
            log.error(f"[{name}] TagoIO connection lost ({e}) — error #{device['consecutive_errors']}")

            if device["consecutive_errors"] >= 5:
                cooldown = 60
                device["cooldown_until"] = time.time() + cooldown
                device["consecutive_errors"] = 0
                log.warning(f"[{name}] Too many errors — cooling down for {cooldown}s")
            else:
                reconnect_tago(device)
                tago_socket = device["tago_socket"]

        except (ModbusException, ConnectionException) as e:
            log.error(f"[{name}] Modbus connection lost ({e}) — reconnecting...")
            client.close()
            device["modbus"] = connect_modbus(device["ip"], name)

        except Exception as e:
            log.error(f"[{name}] Unexpected error ({e})")
            device["consecutive_errors"] += 1
            reconnect_tago(device)

        time.sleep(POLL_INTERVAL)

# --- Main ---
devices = load_devices(DEVICES_FILE)

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