from pymodbus.client import ModbusTcpClient
from pymodbus import FramerType
from pymodbus.exceptions import ConnectionException, ModbusException

# Declare vars
IP = ""  # IP of device to investigate
PORT = 4661  # modbus port
DEVICE_ID = 4

client = ModbusTcpClient(host=IP, port=PORT, framer = FramerType.RTU)

client.read_holding_registers(address=1, count=1, device_id=DEVICE_ID)