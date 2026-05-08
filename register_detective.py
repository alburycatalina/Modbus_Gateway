from pymodbus.client import ModbusTcpClient

IP = "IP HERE" # IP to test
PORT = 502 # port over which it transmits. Usually 502

client = ModbusTcpClient(host=IP, port=PORT)

if not client.connect():
    print("Failed to connect")
    exit()

print("Connected to ADAM-6051")

# --- Read 12 Digital Inputs (DI0-DI11) ---
di_result = client.read_coils(address= "", count="") # FIXME find address and count again
    di_values = di_result.bits[:12]
    for i, val in enumerate(di_values):
        print(f"DI{i}: {'ON' if val else 'OFF'}")
else:
    print(f"Error reading digital inputs: {di_result}")

# --- Read 2 Digital Outputs (DO0-DO1) ---
do_result = client.read_coils(address="", count="") 
if not do_result.isError():
    do_values = do_result.bits[:2]
    for i, val in enumerate(do_values):
        print(f"DO{i}: {'ON' if val else 'OFF'}")
else:
    print(f"Error reading digital outputs: {do_result}")

# --- Read 2 Counters ---
counter_result = client.read_holding_registers(address="", count="")
if not counter_result.isError():
    regs = counter_result.registers
    counter0 = (regs[1] << 16) | regs[0]
    counter1 = (regs[3] << 16) | regs[2]
    print(f"Counter0: {counter0}")
    print(f"Counter1: {counter1}")
else:
    print(f"Error reading counters: {counter_result}")

client.close()