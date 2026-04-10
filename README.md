# Mobus Gateway for ADAM 6051

Need to write gateway for Modbus/TCP to TagoTiP over TCP for process below:

ADAM-6051 (Modbus/TCP)
      ↕  port 502
  Gateway Script
      ↕  TagoTiP over TCP
TagoIO (tcp.tip.us-e1.tago.io:5693)

The ADAM-6051 has 12 digital inputs, 2 counter channels, and 2 digital outputs with 2000 VDC isolation. All digital inputs have a latch function and can be used as counter/frequency input channels. Advantech All of these are readable over Modbus/TCP on port 502.
The Modbus registers we are polling on are:

* Digital inputs (DI0–DI11) — Coils at address 0x0000 onward
* Counter values — Holding registers (32-bit, split into low/high word pairs)
* Digital outputs (DO0–DO1) — Coils readable/writable

## Virtual environment 

Installs required libs - run `.\modbusvenv\Scripts\Activate.ps1` in powershell to activate venv. 


## Required libraries 
A list of required libraries can be found in the `requirements.txt` file. 
[`pymodbus`](https://pymodbus.readthedocs.io/en/latest/): allows for modbus functionality 

## To do
[] Make it so that this script is applied to all of my working devices
[] Write a script that tests which port counts are coming through on
[] front end for the gateway??