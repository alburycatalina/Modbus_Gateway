# Mobus Gateway for DAS Devices

This repository hosts a gateway for IoT devices which transmits Modbus/TCP signals to TagoTiP over TCP. [The main gateway script can be found here.](/modbus_gateway.py) The gateway script polls the devices in `pollees.csv` with [the Pymodbuspackage](https://pymodbus.readthedocs.io/en/latest/index.html) and transmits the requested signals to [Tago.io](tago.io) via [TagoTIP over TCP](https://docs.tago.io/docs/tagotip/transports/tcp). 

## About Devices

### ADAM Devices


In the [ADAM utility software](https://www.advantech.com/en-us/support/details/utility-?id=1-2AKUDB), device settings can be changed and firmware can be updated if needed. MAC addresses for devices can be found in the network tab. Your host PC shows up in the top left corner. Select it and then "search devices" in the toolbar to see what devices are on the network. 

[The 6000 series manual can be found here.](https://www.google.com/url?sa=t&source=web&rct=j&opi=89978449&url=https://advdownload.advantech.com/productfile/Downloadfile4/1-2B6FKTG/ADAM-6000_User_Manaul_Ed.12-FINAL.pdf&ved=2ahUKEwjRyp2OneOTAxUSSjABHWhZJwQQFnoECAwQAQ&usg=AOvVaw1ShTVVehOvGWRFBkxTfZde)


#### ADAM 6051
The ADAM-6051 has 12 digital inputs, 2 counter channels, and 2 digital outputs with 2000 VDC isolation. All digital inputs have a latch function and can be used as counter/frequency input channels. All of these are readable over Modbus/TCP on port 502.

### Serial Servers
To get connected to a new serial server, plug it into your computer and enure it has power. Then, find out what the default IP is and change your computer's IP to something that matches it's first three digits. When that's done, you should be able to visit the device's IP in your browser and assign it a new IP. Connect the device to the ethernet and reassign your normal IP. 

These devices use RTU over TCP rather than just straight up TCP. They connect to devices that don't have their own ethernet connectivity, included below


#### Elkor WattsOn

These devices are used to report on wattage. They can be wired in serial accross three 6 devices (`device_id`) in `pollees.csv` and can have up to three channels that report on voltage and amps. 

[Elkor WattsOn Manual](https://www.elkor.net/pdfs/WattsOn-Mark_II_Manual_Complete.pdf). 

### Quick Network Tips
* In cmd, run `arp -a` to see the list of devices previously connected to PC. 
* In cmd, `for /l %i in (1,1,254) do @ping 10.21.1.%i -n 1 -w 100 | find "Reply"` for all devices on network
* Use `ping (IP address)` to ping a device and see if it is online. 
* To check which registers on a Modbus device are reporting, [see this register detective snippet](/register_detective.py). 


## About  the script

### Adding a Device

Before adding a device you must know it's:
- device type (adam6051, adam6017, elkor_wattsOn). If not one of these, you must add a new encoding to `decode_register_value()` in [modbus_gateway.py](/modbus_gateway.py). To add a new `device_type` you must know:
    1. How many bits the signal requires
    2. Any conversions needed to convert to engineering units via a transformation
This information can be found in the device's manual. 
- IP address. Can often be configured in the device's utility
- serial number: must match serial number in Tago device being added
- protocol: either `tcp` or `rtu_over_tcp`
- device_id: only for `rtu_over_tcp` devices. 
- the registers you need to read on. Use [register_detective.py](/register_detective.py) to find out what registers a signal is transmitting over. 

All of this information must be added to [pollees.csv](/pollees.example.csv). Once added, save the file and re-run the script. 

### Virtual environment

Before installing packages, run `python -m venv /path/to/new/virtual/environment` to create a new virtual enviornment. This creates an isolated directory on your computer that contains its own Python executable and pip libraries, avoiding package conflicts and version issues. 

Run `.\modbusvenv\Scripts\Activate.ps1` in powershell to activate your venv before each session. 

### Required libraries

A list of required libraries can be found in the `requirements.txt` file. Install required packages with `pip install -r requirements.txt`

One of the major libraries used in the script is `[pymodbus](https://pymodbus.readthedocs.io/en/latest/)`.

### Secrets
- `.env` contains a hash code for talking to Tago. It can be found in Tago under Devices > Authorization (top right). [More here](https://docs.tago.io/docs/tagotip/specification/tagotip-specification#2-credentials). This file is also not shared for sercurity purposes. For an example see [`.env.example`](/.env.example). 
- `pollees.csv` contains a list of pollees (AKA devices AKA clients), with a name, IP address, serial number, and registers to read and encoding (16/32 hilo or lohi). It is not pushed to this github for security purposes, but must be in the folder to run the gateway script. See [`pollees.example.csv`](/pollees.example.csv) for an example. 


### `pollees.csv` format

The script supports one or more register points per device. Columns:

- `name`: the internal name for the device
- `device_type`: one of the device types defined in the script's encoding section
- `ip`: device IP address
- `port`: modbus port
- `protocol`: network protocol defined in `run_device()`. either 'tcp' or 'rtu_over_tcp'
- `device_id`: device ID. only used for 'rtu_over_tcp' devices (1-6 for Elkor WattsOn)
- `variable`: contains information about variables

`variables` format: `variable1:address:count;variable2:address:count...`

Eg: countfreq0:24:2 denotes a variable countfreq that uses two positions starting at register 24 (32 bit). Seprate variables coming from the same device as separated by semicolons

- `address` can be hex (`0x18`) or decimal (`24`)
- `count` defaults to `1` and is the number of registers to be read starting at the stated address


Example:

```csv
name,device_type,ip,serial,port,protocol,device_id,variable
device1,adam6051,0.0.0.0,serialnumber1,502,tcp,NA,countfreq0:24:2;countfreq1:26:2
device2,adam6017,0.0.0.0,serialnumber2,502,tcp,NA,volts:7:1
```

### About Modbus Address Notation
The ADAM manual works with the full 5 digit modbus addresses. The Pymodbus package uses a raw, zero based address (multiply by 40000 and add one to the last digit of each number to convert to 5-digit address). 4xxx registers are reserved for read/write output or holding registers. These are used in either decimal or binary in the code. For example:

| Manual Notation | Raw Address (Decimal) | Raw Address (Hex) |
|-------- | ------- |------- |
|40001 | 0 | 0x00 |
|40002 |  1 | 0x01 |
|40025 | 24 | 0x18 |
|40026 | 25 | 0x19 |

### Encoding and Unit Conversion by Device Type

The function `decode_register_value()` defines each device's encoding and unit conversion needs. Based on whether a device is sending 16/32/64 bit signals over registers, encoding and unit conversion are nessary. Some devices send information over 2 registers (32 bit) and others a single one (16 bit). 

| Device | Bits | Engineering Unit | Conversion Formula |
|-------- | ------- |------- |------- |
|ADAM 6051 | 32 | count | registers[0] + registers[1] * 65536 |
|ADAM 6017 |  16 | Volts | (registers[0] / 65535) * 10 |
|Elkor WattsOn | 32 | KwH | concatonate 2 values // int(str(registers[0]) + str(registers[1])) |

### Delta behavior and persisted state

For each configured register point, the gateway sends a current value and delta. 

How `delta` is calculated:

- First sample after startup has no previous value, so `delta = 0`
- Normal case: `delta = current - previous`
- If value wraps and `rollover_bits` is configured, rollover math is applied
- Negative values without a valid rollover are treated as reset/noise and sent as `0`

Previous values are persisted in `last_values.json` so deltas continue across restarts.

### TagoTIP TCP timing (disconnects / `keep_alive_timeout`)

Tago’s TCP endpoints enforce both a keep-alive idle timeout (default 5 seconds) and a connection TTL (default 15 seconds total connection duration on the Scale plan). [More on rate limits.](https://docs.tago.io/docs/tagotip/servers/rate-limits).

This gateway sends periodic `PING` frames during `POLL_INTERVAL` sleeps so the socket does not sit idle longer than the server allows, and reconnects proactively before the connection TTL. Optional environment overrides:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `TAGO_KEEPALIVE_INTERVAL` | `4` | Seconds between uplink frames during idle (must stay below 5). |
| `TAGO_TTL_RECONNECT_BEFORE` | `9` | Proactively reconnect before this many seconds since connect (around 14 on Scale). |

