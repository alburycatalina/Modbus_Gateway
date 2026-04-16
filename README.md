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
## About working with the script

List of pollees, their IP address
### Virtual environment 

Installs required libs - run `.\modbusvenv\Scripts\Activate.ps1` in powershell to activate venv. 


### Required libraries 
A list of required libraries can be found in the `requirements.txt` file. 
[`pymodbus`](https://pymodbus.readthedocs.io/en/latest/): allows for modbus functionality 

## To do
[] Make it so that this script is applied to all of my working devices
[] Write a script that tests which port counts are coming through on
[] front end for the gateway??



## About Working with ADAM devices

In terminal, run `arp -a` to see the list of devices on the network. Use `ping (IP address)` to ping a device and see if it is online. 

[Link to 6000 series manual](https://www.google.com/url?sa=t&source=web&rct=j&opi=89978449&url=https://advdownload.advantech.com/productfile/Downloadfile4/1-2B6FKTG/ADAM-6000_User_Manaul_Ed.12-FINAL.pdf&ved=2ahUKEwjRyp2OneOTAxUSSjABHWhZJwQQFnoECAwQAQ&usg=AOvVaw1ShTVVehOvGWRFBkxTfZde) 

[Link to utility software](https://www.advantech.com/en-us/support/details/utility-?id=1-2AKUDB)

In this utility, device settings can be changed and firmware can be updated if needed. MAC addresses for devices can be found in the network tab. Your host PC shows up in the top left corner. Select it and then "search devices" in the toolbar to see what devices are on the network. 