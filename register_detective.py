# Import modbus library
from pymodbus.client import ModbusTcpClient

# Declare vars
IP = "10.21.1.169" # IP of device to investigate 
PORT = 502 # modbus port

# Function for getting all registers, from 65536
def read_all_registers(client):
    """Read all holding registers, return dict of {raw_address: value}"""
    registers = {}
    for start in range(0, 65536, 125):
        count = min(125, 65536 - start)
        result = client.read_holding_registers(address=start, count=count)
        if not result.isError():
            for i, value in enumerate(result.registers):
                registers[start + i] = value
    return registers

# Establish connection to client 
client = ModbusTcpClient(host=IP, port=PORT)

# Scan registers twice and see what the difference between them is 
# Run script, make device send signal (ex: close the circuit on a count port) and then hit enter
# If there is a register reporting, the value should have changed and it will print out
if client.connect():
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