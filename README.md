# podtana
Bridge from USB Line 6 POD HD 400 to Boss Katana MKII (100 etc), Also advertises controller as virtual midi output

- Intended for use on linux (Raspberry PI etc with 2x USB inputs)
- Should work for POD HS 300, POD HD 500 as well
- Reads raw midi from the device USB endpoint

Requirements:
- Linux
- Python

Requires user permissions for usb device:
`sudo nano /etc/udev/rules.d/50-myusb.rules`

All all users to read/write to the controller
`SUBSYSTEMS=="usb", ATTRS{idVendor}=="0e41", ATTRS{idProduct}=="5058", GROUP="users", MODE="0666"`

To start script on device connection (or boot), specify a user and path:
`SUBSYSTEMS=="usb", ATTRS{idVendor}=="0e41", ATTRS{idProduct}=="5058", GROUP="users", MODE="0666", RUN+="/bin/su theuser -c '/usr/bin/python /home/theuser/pyusb/podtana.py'"`
