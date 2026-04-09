import time
import socket
from datetime import datetime
from pymodbus.client import ModbusTcpClient
from dotenv import load_dotenv
import os

load_dotenv()
AUTH_HASH = os.getenv("AUTH_HASH")
SERIAL = os.getenv("SERIAL")

ADAM_IP = "10.21.1.166"
ADAM_PORT = 502
POLL_INTERVAL = 3
PING_INTERVAL = 30

TAGO_HOST = "tcp.tip.us-e1.tago.io"
TAGO_PORT = 5693

# Connect to ADAM-6051
modbus_client = ModbusTcpClient(host=ADAM_IP, port=ADAM_PORT)
if not modbus_client.connect():
    print("Failed to connect to ADAM-6051")
    exit()
print("Connected to ADAM-6051")

def connect_tago():
    """Create and return a fresh TagoIO socket connection."""
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((TAGO_HOST, TAGO_PORT))
            print("Connected to TagoIO")
            return sock
        except Exception as e:
            print(f"Failed to connect to TagoIO: {e} — retrying in 3s")
            time.sleep(5)

def send_frame(sock, frame):
    """Send a frame and return the ACK response."""
    sock.sendall(frame.encode())
    return sock.recv(1024).decode().strip()

tago_socket = connect_tago()
last_ping = time.time()

try:
    while True:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Send PING if due
            if time.time() - last_ping >= PING_INTERVAL:
                ping_frame = f"PING|{AUTH_HASH}|{SERIAL}\n"
                ack = send_frame(tago_socket, ping_frame)
                print(f"[{timestamp}] PING: {ack}")
                last_ping = time.time()

            # Read from ADAM and send to TagoIO
            reg_result = modbus_client.read_holding_registers(address=0x0018, count=1)
            if not reg_result.isError():
                freq = reg_result.registers[0]
                frame = f"PUSH|{AUTH_HASH}|{SERIAL}|[countfreq:={freq}#Hz]\n"
                ack = send_frame(tago_socket, frame)
                print(f"[{timestamp}] Sent: {frame.strip()}")
                print(f"[{timestamp}] ACK:  {ack}")
            else:
                print(f"[{timestamp}] Error reading ADAM: {reg_result}")

        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError) as e:
            print(f"[{timestamp}] TagoIO connection lost: {e} — reconnecting...")
            tago_socket.close()
            tago_socket = connect_tago()
            last_ping = time.time()

        time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    print("\nStopping...")
finally:
    modbus_client.close()
    tago_socket.close()
    print("Disconnected")