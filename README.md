# Mobus Gateway for ADAM 6051

This script is a gateway for IoT devices which transmits Modbus/TCP to TagoTiP over TCP. 

General workflow:

Device or "pollee" (via Modbus/TCP) <- port 502 -> Gateway Script <-TagoTiP over TCP -> TagoIO (tcp.tip.us-e1.tago.io:5693)



## About Devices

In terminal, run `arp -a` to see the list of devices on the network. Use `ping (IP address)` to ping a device and see if it is online. To check the registers on a Modbus device, [see this register detective snippet](/register_detective.py). 

### ADAM 


In the [ADAM utility software](https://www.advantech.com/en-us/support/details/utility-?id=1-2AKUDB), device settings can be changed and firmware can be updated if needed. MAC addresses for devices can be found in the network tab. Your host PC shows up in the top left corner. Select it and then "search devices" in the toolbar to see what devices are on the network. [The 6000 series manual can be found here.](https://www.google.com/url?sa=t&source=web&rct=j&opi=89978449&url=https://advdownload.advantech.com/productfile/Downloadfile4/1-2B6FKTG/ADAM-6000_User_Manaul_Ed.12-FINAL.pdf&ved=2ahUKEwjRyp2OneOTAxUSSjABHWhZJwQQFnoECAwQAQ&usg=AOvVaw1ShTVVehOvGWRFBkxTfZde)


#### ADAM 6051
The ADAM-6051 has 12 digital inputs, 2 counter channels, and 2 digital outputs with 2000 VDC isolation. All digital inputs have a latch function and can be used as counter/frequency input channels. All of these are readable over Modbus/TCP on port 502.
The Modbus registers we are polling on are:

- Digital inputs (DI0–DI11) — Coils at address 0x0000 onward
- Counter values — Holding registers (32-bit, split into low/high word pairs)
- Digital outputs (DO0–DO1) — Coils readable/writable

## About  the script

### Required libraries

A list of required libraries can be found in the `requirements.txt` file. Install required packages with `pip install -r requirements.txt`
`[pymodbus](https://pymodbus.readthedocs.io/en/latest/)`: allows for modbus functionality 

### Virtual environment

Run `.\modbusvenv\Scripts\Activate.ps1` in powershell to activate the venv. This creates an isolated directory on your computer that contains its own Python executable and pip libraries, avoiding package conflicts and version issues. 

### Secrets
- [`pollees.csv`](/pollees.csv) contains a list of pollees, with a name, IP address, and serial number. It is not pushed to this github for security purposes, but must be in the folder so that it can be accessed by the gateway script. See [`pollees.example.csv`](/pollees.example.csv) for an example. 
- `.env` contains a hash code for talking to Tago. It can be found in Tago under Devices > Authorization (top right). [More here](https://docs.tago.io/docs/tagotip/specification/tagotip-specification#2-credentials). This file is also not shared for sercurity purposes. For an example see [`.env.example`](/.env.example). 

### `pollees.csv` format

The script supports one or more register points per device.

- Required columns: `name`, `ip`, `serial`
- Preferred config column: `registers`
- Legacy fallback columns still supported: `register_address`, `register_count`, `variable_name`

`registers` format:

- `variable:address[:count[:rollover_bits]];variable2:address[:count[:rollover_bits]]`
- `address` can be hex (`0x18`) or decimal (`24`)
- `count` defaults to `1`
- `rollover_bits` defaults to `16 * count`

The ADAM manual works with the full 5 digit modbus addresses. Pymodbus package uses a raw, zero based address (multiply by 40000 and add one to the last digit of each number to convert to 5-digit address). 4xxx registers are reserved for read/write output or holding registers. For example:

| Manual Notation | Raw Address |
|-------- | ------- |
|40001 | 0 |
|40002 |  1 |
|40025 | 24 |
|40026 | 25 |

Example:

```csv
name,ip,serial,registers
adam-6051-a,192.168.1.50,EXAMPLE_SERIAL_001,countfreq:0x18:1:16
adam-6051-b,192.168.1.51,EXAMPLE_SERIAL_002,countfreq:0x18:1:16;total_count:0x20:2:32
```

### Delta behavior and persisted state

For each configured register point, the gateway sends:

- Current value: `[variable:=value]`
- Delta value: `[variable_delta:=delta]`

How `delta` is calculated:

- First sample after startup has no previous value, so `delta = 0`
- Normal case: `delta = current - previous`
- If value wraps and `rollover_bits` is configured, rollover math is applied
- Negative values without a valid rollover are treated as reset/noise and sent as `0`

Previous values are persisted in `last_values.json` so deltas continue across restarts.


