import time
import socket
import csv
from datetime import datetime
from pymodbus.client import ModbusTcpClient
from dotenv import load_dotenv
import os

load_dotenv()
AUTH_HASH = os.getenv("AUTH_HASH")
ADAM_PORT = 502
POLL_INTERVAL = 3 # poll every 3 secs
PING_INTERVAL = 30 # ping every 30 secs
TAGO_HOST = "tcp.tip.us-e1.tago.io"
TAGO_PORT = 5693
DEVICES_FILE = "pollees.csv"

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
    print(f"Loaded {len(devices)} device(s) from {DEVICES_FILE}")
    return devices

# Make connection to modbus slaves with pymodbus
def connect_modbus(ip, name):
    """Connect to an ADAM device, retrying until successful."""
    while True:
        client = ModbusTcpClient(host=ip, port=ADAM_PORT)
        if client.connect():
            print(f"Connected to ADAM [{name}] at {ip}")
            return client
        print(f"Failed to connect to ADAM [{name}] at {ip} — retrying in 5s")
        time.sleep(5)

# format modbus info into Tagosocket info 
def connect_tago():
    """Create and return a fresh TagoIO socket connection."""
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((TAGO_HOST, TAGO_PORT))
            print("Connected to TagoIO")
            return sock
        except Exception as e:
            print(f"Failed to connect to TagoIO: {e} — retrying in 5s")
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
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S") #get a timestamp for sending data

        for device in devices:
            name   = device["name"]
            serial = device["serial"]
            client = device["modbus"]

            try:
                # Send PING if due
                if time.time() - device["last_ping"] >= PING_INTERVAL:
                    ping_frame = f"PING|{AUTH_HASH}|{serial}\n"
                    ack = send_frame(tago_socket, ping_frame)
                    print(f"[{timestamp}] [{name}] PING: {ack}")
                    device["last_ping"] = time.time()

                # Read from ADAM and send to TagoIO
                reg_result = client.read_holding_registers(address=0x0018, count=1)
                if not reg_result.isError():
                    freq = reg_result.registers[0]
                    frame = f"PUSH|{AUTH_HASH}|{serial}|[countfreq:={freq}]\n"
                    ack = send_frame(tago_socket, frame)
                    print(f"[{timestamp}] [{name}] Sent: {frame.strip()}")
                    print(f"[{timestamp}] [{name}] ACK:  {ack}")
                else:
                    print(f"[{timestamp}] [{name}] Error reading ADAM: {reg_result}")

            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError) as e:
                print(f"[{timestamp}] TagoIO connection lost: {e} — reconnecting...")
                tago_socket.close()
                tago_socket = connect_tago()
                device["last_ping"] = time.time()

            except Exception as e:
                print(f"[{timestamp}] [{name}] Modbus error: {e} — reconnecting...")
                client.close()
                device["modbus"] = connect_modbus(device["ip"], name)

        time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    print("\nStopping...")
finally:
    for device in devices:
        device["modbus"].close()
    tago_socket.close()
    print("Disconnected")