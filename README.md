# podtana
Bridge from USB Line 6 POD HD 400 to Boss Katana MKII (100 etc), Also advertises controller as virtual midi output

- Intended for use on linux (Raspberry PI etc with 2x USB inputs)

Requirements:
- Linux
- Python

Requires user permissions for usb device:
`sudo nano /etc/udev/rules.d/50-myusb.rules`

`SUBSYSTEMS=="usb", ATTRS{idVendor}=="0e41", ATTRS{idProduct}=="5058", GROUP="users", MODE="0666"`