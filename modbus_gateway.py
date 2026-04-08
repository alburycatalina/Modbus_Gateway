from pymodbus.client import ModbusTcpClient

ADAM_IP = "10.21.1.173"  # Replace with your ADAM-6051's IP address
ADAM_PORT = 502

client = ModbusTcpClient(host=ADAM_IP, port=ADAM_PORT)

if client.connect():
    print("Connected to ADAM-6051")
    client.close()
else:
    print("Failed to connect")