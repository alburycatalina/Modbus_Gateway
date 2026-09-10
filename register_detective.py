import time
from pymodbus.client import ModbusTcpClient

# ----------------------------
# Config
# ----------------------------
IP = "10.21.1.161"      # IP of device to investigate
PORT = 4661               # modbus port (use serial server's TCP port for rtuOverTCP)
DRIVER = "rtuOverTCP"           # "tcp" or "rtuOverTCP"
DEVICE_ID = 1            # RTU slave address, only used for rtuOverTCP


# ----------------------------
# Drivers - rtu or rtuOverTCP
# ----------------------------
class ModbusTCPDriver:
    """ Modbus TCP """
    def __init__(self, ip, port=502):
        self.ip = ip
        self.port = port
        self.client = None

    def connect(self):
        while True:
            self.client = ModbusTcpClient(host=self.ip, port=self.port)
            if self.client.connect():
                return
            time.sleep(5)

    def read_registers(self, address, count):
        return self.client.read_holding_registers(address=address, count=count)

    def close(self):
        if self.client:
            self.client.close()


class ModbusRTUOverTCPDriver:
    """Modbus RTU framed over TCP — serial server devices."""
    def __init__(self, ip, port, device_id):
        self.ip = ip
        self.port = port            # 4661 or 4660
        self.device_id = device_id  # maps to `slave=` in pymodbus
        self.client = None

    def connect(self):
        while True:
            # framer="rtu" tells pymodbus to use RTU framing over the TCP socket
            self.client = ModbusTcpClient(
                host=self.ip,
                port=self.port,
                framer="rtu",
            )
            if self.client.connect():
                return
            time.sleep(5)

    def read_registers(self, address, count):
        # device_id is the RTU slave address
        return self.client.read_holding_registers(
            address=address,
            count=count,
            device_id=self.device_id,
        )

    def close(self):
        if self.client:
            self.client.close()


def get_driver(driver_name, ip, port, device_id=None):
    """Set protocol based on DRIVER"""
    if driver_name == "tcp":
        return ModbusTCPDriver(ip, port)
    elif driver_name == "rtuOverTCP":
        return ModbusRTUOverTCPDriver(ip, port, device_id)
    else:
        raise ValueError(f"Unknown driver: {driver_name}")


# ----------------------------
# Scan registers
# ----------------------------
def read_all_registers(driver):
    """Read all holding registers, return dict of {raw_address: value}"""
    registers = {}
    for start in range(0, 65536, 125):
        count = min(125, 65536 - start)
        result = driver.read_registers(start, count)
        if not result.isError():
            for i, value in enumerate(result.registers):
                registers[start + i] = value
    return registers


# ----------------------------
# Main
# ----------------------------
driver = get_driver(DRIVER, IP, PORT, DEVICE_ID)
driver.connect()

# Scan registers twice and see what the difference between them is
# Run script, make device send signal (close circuit by tapping relevant wires together) and then hit enter in terminal
# If there is a register reporting, the value should have changed and it will print out
print("First scan...")
scan_1 = read_all_registers(driver)

input("\nFirst scan complete. Press Enter to start second scan...")

print("Second scan...")
scan_2 = read_all_registers(driver)

driver.close()

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