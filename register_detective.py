# Import modbus library
from pymodbus.client import ModbusTcpClient
from pymodbus import FramerType
from pymodbus.exceptions import ConnectionException, ModbusException

# Declare vars
IP = ""  # IP of device to investigate
PORT = ""  # modbus port
DEVICE_ID = ""

# Connection type: "tcp" for standard Modbus TCP, "rtu_over_tcp" for RTU framing
# over a raw TCP socket (e.g. GW312 serial server in transparent/bridge mode)
CONNECTION_TYPE = "rtu_over_tcp"  # "tcp" or "rtu_over_tcp"

FRAMER_MAP = {
    "tcp": FramerType.SOCKET,
    "rtu_over_tcp": FramerType.RTU,
}


def make_client(connection_type):
    """Build a ModbusTcpClient with the framer appropriate to the connection type."""
    if connection_type not in FRAMER_MAP:
        raise ValueError(f"Unknown connection type: {connection_type}")
    return ModbusTcpClient(host=IP, port=PORT, framer=FRAMER_MAP[connection_type])


# Function for getting all registers, from 65536
def read_all_registers(client):
    """Read all holding registers, return dict of {raw_address: value}"""
    registers = {}
    for start in range(0, 65536, 125):
        count = min(125, 65536 - start)
        result = client.read_holding_registers(address=start, count=count, device_id=DEVICE_ID)
        if not result.isError():
            for i, value in enumerate(result.registers):
                registers[start + i] = value
    return registers


# Establish connection to client
client = make_client(CONNECTION_TYPE)

# Scan registers twice and see what the difference between them is
# Run script, make device send signal (ex: close the circuit on a count port) and then hit enter
# If there is a register reporting, the value should have changed and it will print out
if client.connect():
    print(f"Connected using '{CONNECTION_TYPE}' framing ({FRAMER_MAP[CONNECTION_TYPE]})")
    print("First scan...")
    scan_1 = read_all_registers(client)
    input("\nFirst scan complete. Press Enter to start second scan...")
    print("Second scan...")
    scan_2 = read_all_registers(client)
    client.close()

    # Compare the two scans
    changing = []
    for reg_addr in scan_1:
        if reg_addr in scan_2 and scan_1[reg_addr] != scan_2[reg_addr]:
            changing.append((reg_addr, scan_1[reg_addr], scan_2[reg_addr]))

    print("\n--- Changing Registers ---")
    if changing:
        print(f"{'Manual Notation':<20} {'Raw Address':<15} {'Scan 1':<15} {'Scan 2'}")
        print("-" * 65)
        for raw_addr, val1, val2 in changing:
            modbus_notation = 40001 + raw_addr
            print(f"{modbus_notation:<20} {raw_addr:<15} {val1:<15} {val2}")
    else:
        print("No registers changed between scans.")
else:
    print("Failed to connect")