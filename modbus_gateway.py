import time
import socket
import csv
import logging
from datetime import datetime
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException, ConnectionException
from dotenv import load_dotenv
import os

load_dotenv()
AUTH_HASH = os.getenv("AUTH_HASH")
ADAM_PORT = 502
POLL_INTERVAL = 10 # poll every 20 secs
PING_INTERVAL = 30 # ping every 30 secs
TAGO_HOST = "tcp.tip.us-e1.tago.io"
TAGO_PORT = 5693
DEVICES_FILE = "pollees.csv"
LOG_FILE = "poller.log"

# Configure logging to write to a .txt file
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Load devices info (name, IP, serial)
def load_devices(DEVICES_FILE):
    """Load devices from CSV file."""
    devices = []
    with open(DEVICES_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            devices.append({
                "name":   row["name"],
                "ip":     row["ip"],
                "serial": row["serial"],
            })
    log.info(f"Loaded {len(devices)} device(s) from {DEVICES_FILE}")
    return devices

# Make connection to modbus slaves with pymodbus
def connect_modbus(ip, name):
    """Connect to an ADAM device, retrying until successful."""
    while True:
        client = ModbusTcpClient(host=ip, port=ADAM_PORT)
        if client.connect():
            log.info(f"Connected to ADAM [{name}] at {ip}")
            return client
        log.warning(f"Failed to connect to ADAM [{name}] at {ip} — retrying in 5s")
        time.sleep(5)

# Create tago socket connection
def connect_tago():
    """Create and return a fresh TagoIO socket connection."""
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(None)
            sock.connect((TAGO_HOST, TAGO_PORT))
            log.info("Connected to TagoIO")
            return sock
        except Exception as e:
            log.warning(f"Failed to connect to TagoIO: {e} — retrying in 5s")
            time.sleep(5)

def send_frame(sock, frame):
    """Send a frame and return the ACK response."""
    sock.sendall(frame.encode())
    return sock.recv(1024).decode().strip()

# Load devices and connect to all of them
devices = load_devices(DEVICES_FILE)
for device in devices:
    device["modbus"] = connect_modbus(device["ip"], device["name"])
    device["last_ping"] = time.time()

tago_socket = connect_tago()

try:
    while True:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for device in devices:
            name   = device["name"]
            serial = device["serial"]
            client = device["modbus"]

            try:
                # Send PING if due
                if time.time() - device["last_ping"] >= PING_INTERVAL:
                    ping_frame = f"PING|{AUTH_HASH}|{serial}\n"
                    ack = send_frame(tago_socket, ping_frame)
                    log.info(f"[{name}] PING: {ack}")
                    device["last_ping"] = time.time()

                    # Read from ADAM and send to TagoIO
                    reg_result = client.read_holding_registers(address=0x0018, count=1)

                    if reg_result is None or reg_result.isError():
                        log.warning(f"[{name}] Modbus read failed — reconnecting...")
                        client.close()
                        device["modbus"] = connect_modbus(device["ip"], name)
                        continue  # Skip to next device, try again next poll cycle

                    freq = reg_result.registers[0]
                    frame = f"PUSH|{AUTH_HASH}|{serial}|[countfreq:={freq}]\n"
                    ack = send_frame(tago_socket, frame)
                    log.info(f"[{name}] Sent: {frame.strip()}")
                    log.info(f"[{name}] ACK:  {ack}")

            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError) as e:
                log.error(f"[{timestamp}] TagoIO connection lost ({e}) — reconnecting...")
                tago_socket.close()
                tago_socket = connect_tago()
                last_reconnect = time.time()
                device["last_ping"] = time.time()

            except (ModbusException, ConnectionException) as e:
                log.error(f"[{timestamp}] [{name}] Modbus connection lost ({e}) — reconnecting...")
                client.close()
                device["modbus"] = connect_modbus(device["ip"], name)

            except Exception as e:
                log.error(f"[{timestamp}] [{name}] Unexpected error ({e}) — reconnecting Modbus...")
                client.close()
                device["modbus"] = connect_modbus(device["ip"], name)

        time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    log.info("Stopping — KeyboardInterrupt received.")
finally:
    for device in devices:
        device["modbus"].close()
    tago_socket.close()
    log.info("Disconnected.")