# Mobus Gateway for DAS Devices

This script is a gateway for IoT devices which transmits Modbus/TCP signals to TagoTiP over TCP. 

General workflow:

Device or "pollee" (via Modbus/TCP) <- port 502 -> Gateway Script <-TagoTiP over TCP -> TagoIO (tcp.tip.us-e1.tago.io:5693)

## About Devices

* In terminal, run `arp -a` to see the list of devices on the network. 
* Use `ping (IP address)` to ping a device and see if it is online. 
* To check which registers on a Modbus device are reporting, [see this register detective snippet](/register_detective.py). 

### ADAM Devices


In the [ADAM utility software](https://www.advantech.com/en-us/support/details/utility-?id=1-2AKUDB), device settings can be changed and firmware can be updated if needed. MAC addresses for devices can be found in the network tab. Your host PC shows up in the top left corner. Select it and then "search devices" in the toolbar to see what devices are on the network. 

[The 6000 series manual can be found here.](https://www.google.com/url?sa=t&source=web&rct=j&opi=89978449&url=https://advdownload.advantech.com/productfile/Downloadfile4/1-2B6FKTG/ADAM-6000_User_Manaul_Ed.12-FINAL.pdf&ved=2ahUKEwjRyp2OneOTAxUSSjABHWhZJwQQFnoECAwQAQ&usg=AOvVaw1ShTVVehOvGWRFBkxTfZde)


#### ADAM 6051
The ADAM-6051 has 12 digital inputs, 2 counter channels, and 2 digital outputs with 2000 VDC isolation. All digital inputs have a latch function and can be used as counter/frequency input channels. All of these are readable over Modbus/TCP on port 502.


## About  the script

### Virtual environment

Before installing packages, run `python -m venv /path/to/new/virtual/environment` to create a new virtual enviornment. This creates an isolated directory on your computer that contains its own Python executable and pip libraries, avoiding package conflicts and version issues. 

Run `.\modbusvenv\Scripts\Activate.ps1` in powershell to activate your venv before each session. 

### Required libraries

A list of required libraries can be found in the `requirements.txt` file. Install required packages with `pip install -r requirements.txt`

One of the major libraries used in the script is `[pymodbus](https://pymodbus.readthedocs.io/en/latest/)`.

### Secrets
- `.env` contains a hash code for talking to Tago. It can be found in Tago under Devices > Authorization (top right). [More here](https://docs.tago.io/docs/tagotip/specification/tagotip-specification#2-credentials). This file is also not shared for sercurity purposes. For an example see [`.env.example`](/.env.example). 
- [`pollees.csv`](/pollees.csv) contains a list of pollees (AKA devices AKA clients), with a name, IP address, serial number, and registers to read and encoding (16/32 hilo or lohi). It is not pushed to this github for security purposes, but must be in the folder to run the gateway script. See [`pollees.example.csv`](/pollees.example.csv) for an example. 


#### `pollees.csv` format

The script supports one or more register points per device.

- Required columns: `name`, `ip`, `serial`
- Preferred config column: `registers`
- Legacy fallback columns still supported: `register_address`, `register_count`, `variable_name`

`registers` format: `variable:address:count:rollover_bits:encoding`

Eg: countfreq:24:2:32:uint32_lohi denotes a variable countfreq that uses two positions starting at register 24 (32 bit) and a lohi encoding. 


- `address` can be hex (`0x18`) or decimal (`24`)
- `count` defaults to `1`
- `rollover_bits` defaults to `16 * count`
- `encoding` specifies if a device's registers use hilo or lohi encoding

Example:

```csv
name,ip,serial,registers
adam-6051-a,192.168.1.50,EXAMPLE_SERIAL_001,countfreq:0x18:1:16:uint32lohi
adam-6051-b,192.168.1.51,EXAMPLE_SERIAL_002,countfreq:0x18:1:16:uint32lohi;total_count:0x20:2:32
```
##### About Modbus Address Notation
The ADAM manual works with the full 5 digit modbus addresses. Pymodbus package uses a raw, zero based address (multiply by 40000 and add one to the last digit of each number to convert to 5-digit address). 4xxx registers are reserved for read/write output or holding registers. These are used in either decimal or binary in the code. For example:

| Manual Notation | Raw Address (Decimal) | Raw Address (Hex) |
|-------- | ------- |------- |
|40001 | 0 | 0x00 |
|40002 |  1 | 0x01 |
|40025 | 24 | 0x18 |
|40026 | 25 | 0x19 |



### Delta behavior and persisted state

For each configured register point, the gateway sends a current value and delta. 

How `delta` is calculated:

- First sample after startup has no previous value, so `delta = 0`
- Normal case: `delta = current - previous`
- If value wraps and `rollover_bits` is configured, rollover math is applied
- Negative values without a valid rollover are treated as reset/noise and sent as `0`

Previous values are persisted in `last_values.json` so deltas continue across restarts.

### TagoTIP TCP timing (disconnects / `keep_alive_timeout`)

Tago’s TCP endpoints enforce both a **keep-alive idle timeout** (default **5 seconds** without any uplink frame) and a **connection TTL** (default **10 seconds** total connection duration on Free/Starter, **15 seconds** on Scale). Details: [Rate limits](https://docs.tago.io/docs/tagotip/servers/rate-limits).

This gateway sends periodic `PING` frames during `POLL_INTERVAL` sleeps so the socket does not sit idle longer than the server allows, and reconnects proactively before the connection TTL. Optional environment overrides:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `TAGO_KEEPALIVE_INTERVAL` | `4` | Seconds between uplink frames during idle (must stay **below 5**). |
| `TAGO_TTL_RECONNECT_BEFORE` | `9` | Proactively reconnect before this many seconds since connect (under **10** on Free/Starter, around **14** on Scale). |

