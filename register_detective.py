from pymodbus.client import ModbusTcpClient

IP = ""  # Device IP here
PORT = 502 # port for modus
SLAVE_ID = 1

client = ModbusTcpClient(host=IP, port=PORT)

if client.connect():
    non_zero_registers = []
    
    # Holding registers: 0–65535
    print("Scanning all holding registers (0–65535)...")
    for start in range(0, 65536, 125):  # Read in chunks of 125 (max per request)
        count = min(125, 65536 - start)
        result = client.read_holding_registers(address=start, count=count)
        
        if not result.isError():
            for i, value in enumerate(result.registers):
                reg_num = start + i
                if value != 0:
                    non_zero_registers.append((reg_num, value))
        else:
            print(f"  Error reading registers {start}–{start + count - 1}: {result}")

    client.close()

    print("\n--- Active Raw Zero Based Addresses ---")
    if non_zero_registers:
        for reg_num, value in non_zero_registers:
            print(f"  Register {reg_num}: {value}")
    else:
        print("  All registers are 0 (or unreadable).")
else:
    print("Failed to connect")
