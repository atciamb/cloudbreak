#!/bin/bash
# Cloudbreak USB gadget on the Pi Zero 2 W's USB *data* port (the one marked USB, not PWR IN):
#   - RNDIS network adapter. Microsoft OS descriptors make Windows bind its in-box driver; no install on the laptop.
#     NetworkManager gives usb0 the bench address 169.254.77.2/16 (profile cloudbreak-usb0); Windows falls back to
#     a 169.254.x.x address on its side, so `ssh pidrone@169.254.77.2` works as it did over the Pi 3's ethernet.
#   - CDC-ACM serial console (Windows: "USB Serial Device (COMx)"), a fallback login if networking misbehaves.
# Needs `dtoverlay=dwc2,dr_mode=peripheral` in config.txt ([pi02] section). On boards without a USB device
# controller (Pi 3) it does nothing. Installed as /usr/local/sbin/cloudbreak-usb-gadget, run by
# cloudbreak-usbgadget.service at boot.
set -eu
G=/sys/kernel/config/usb_gadget/cloudbreak

modprobe dwc2 2>/dev/null || true
UDC=""
for _ in $(seq 1 20); do                     # dwc2 binds via udev coldplug; give it up to 10 s
  UDC=$(ls /sys/class/udc 2>/dev/null | head -n1 || true)
  [ -n "$UDC" ] && break
  sleep 0.5
done
if [ -z "$UDC" ]; then
  echo "cloudbreak-usb-gadget: no USB device controller (not a Zero, or dtoverlay=dwc2 missing); nothing to do"
  exit 0
fi

modprobe libcomposite
mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config

if [ -d "$G" ] && [ -n "$(cat "$G/UDC" 2>/dev/null || true)" ]; then
  echo "cloudbreak-usb-gadget: already bound to $(cat "$G/UDC")"
  exit 0
fi

if [ ! -d "$G" ]; then
  SERIAL=$(tr -d '\0' </proc/device-tree/serial-number 2>/dev/null || echo cloudbreak)
  mkdir -p "$G"
  echo 0x1d6b >"$G/idVendor"                # Linux Foundation
  echo 0x0104 >"$G/idProduct"               # Multifunction Composite Gadget
  echo 0x0101 >"$G/bcdDevice"
  echo 0x0200 >"$G/bcdUSB"
  echo 0xEF >"$G/bDeviceClass"              # misc / interface association: Windows splits the functions
  echo 0x02 >"$G/bDeviceSubClass"
  echo 0x01 >"$G/bDeviceProtocol"
  mkdir -p "$G/strings/0x409"
  echo "$SERIAL" >"$G/strings/0x409/serialnumber"
  echo "Cloudbreak" >"$G/strings/0x409/manufacturer"
  echo "Cloudbreak Pi Zero 2 W" >"$G/strings/0x409/product"

  echo 1 >"$G/os_desc/use"                  # Microsoft OS descriptors -> Windows loads its RNDIS driver
  echo 0xcd >"$G/os_desc/b_vendor_code"
  echo MSFT100 >"$G/os_desc/qw_sign"

  mkdir -p "$G/functions/rndis.usb0"
  echo 02:cb:5a:00:00:01 >"$G/functions/rndis.usb0/host_addr"   # fixed MACs: Windows keeps one adapter, not
  echo 02:cb:5a:00:00:02 >"$G/functions/rndis.usb0/dev_addr"    # a new "Network N" every boot
  echo RNDIS >"$G/functions/rndis.usb0/os_desc/interface.rndis/compatible_id"
  echo 5162001 >"$G/functions/rndis.usb0/os_desc/interface.rndis/sub_compatible_id"
  mkdir -p "$G/functions/acm.GS0"

  mkdir -p "$G/configs/c.1/strings/0x409"
  echo "RNDIS network + serial console" >"$G/configs/c.1/strings/0x409/configuration"
  echo 0x80 >"$G/configs/c.1/bmAttributes"
  echo 250 >"$G/configs/c.1/MaxPower"
  ln -s "$G/functions/rndis.usb0" "$G/configs/c.1/"   # RNDIS must be the first interface for Windows
  ln -s "$G/functions/acm.GS0" "$G/configs/c.1/"
  ln -s "$G/configs/c.1" "$G/os_desc/"
fi

echo "$UDC" >"$G/UDC"
echo "cloudbreak-usb-gadget: bound to $UDC (usb0 = RNDIS, ttyGS0 = serial console)"
