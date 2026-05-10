from pymodbus.client import ModbusTcpClient

IP = "IP HERE" # IP to test
PORT = 502 # port over which it transmits. Usually 502

client = ModbusTcpClient(host=IP, port=PORT)

if not client.connect():
    print("Failed to connect")
    exit()

print("Connected to device")

# Address found in manual 
client.read_coils(address=0x0000, count=12) 

client.close()