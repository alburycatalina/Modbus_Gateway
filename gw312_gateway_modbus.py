from pymodbus.client import ModbusSerialClient, ModbusTcpClient
from pymodbus.framer import FramerType
import time

# Beachhouse (IP HERE) has 5 elkors in serial reporting on various BEC lines
# TODO figure out what the register numbers of "monitor points" 1-3 on Elkors
# Elkor: 9600 baud, RS-485, Modbus RTU wrapped in a TCP packet

# TODO why can't I connect to 166?

# Variables
device_id = 1
host_ip = ""  
host_port = 4661

# Connect client
client = ModbusTcpClient(
    host= host_ip,
    port= host_port,
    framer=FramerType.RTU # tell pymodbus to use RTU framing over TCP
)

client.connect()

# Need devc
# 0x00-0x01 total energy consumption (32 bit, signed, big endendian )
# to get 32 bit number, concat both readings (Wh)
result = client.read_holding_registers(address=0x350, 
                                       count=2, 
                                       device_id = device_id)
print(result.registers)

client.close()

# For discovering device numbers 
# Works with 161 and shows 5 devices
# for device_id in range(1, 6):
#     try:
#         result = client.read_holding_registers(address=40008, count=1, device_id=device_id)
#         if not result.isError():
#             print(f"Found device at ID: {device_id}")
#         client.close()
#         time.sleep(0.1)  # small delay to let the server reset
#     except Exception as e:
#         client.close()
#         pass