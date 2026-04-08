import time
from datetime import datetime
from pymodbus.client import ModbusTcpClient

ADAM_IP = "10.21.1.166"
ADAM_PORT = 502
POLL_INTERVAL = 1  # seconds

# Connect to client 
client = ModbusTcpClient(host=ADAM_IP, port=ADAM_PORT)

if not client.connect(): # error if fail to connect 
    print("Failed to connect")
    exit()

print("Connected to ADAM-6051") # sucess message if connection 

try:
    while True:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # print date 

        reg_result = client.read_holding_registers(address=0x0018, count=1) # This address is where the counter frequency reports from 
        if not reg_result.isError():
            freq = reg_result.registers[0]
            print(f"[{timestamp}] Count: {freq}")
        else:
            print(f"[{timestamp}] Error reading count: {reg_result}")

        time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    print("\nStopping...")
finally:
    client.close()
    print("Disconnected")