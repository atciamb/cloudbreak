#!/bin/bash
# Install the Zero 2 W's USB network link to the laptop. Idempotent; safe on a Pi 3 (the gadget then does nothing).
#   sudo bash usbnet_install.sh [SRC_DIR]     # SRC_DIR holds usb_gadget.sh and systemd/cloudbreak-usbgadget.service
# Called by setup_pi.sh, and once at boot by usbnet_firstrun.sh when scripts/sd_usbnet.py prepared the SD card on
# the laptop (the card cannot be reached over the network until this has run).
#   - config.txt [pi02]: dtoverlay=dwc2,dr_mode=peripheral (the data port becomes a USB device; Zero 2 W only)
#   - /usr/local/sbin/cloudbreak-usb-gadget + cloudbreak-usbgadget.service (RNDIS + serial gadget at boot)
#   - NetworkManager profile cloudbreak-usb0: usb0 = 169.254.77.2/16, never the default route (Wi-Fi keeps that),
#     plus a udev rule so NetworkManager manages the gadget interface at all
#   - serial-getty on ttyGS0 (login prompt on the laptop's COM port; password login only)
# CB_ROOT prefixes every path (tests only).
set -eu
S="${1:-$(cd "$(dirname "$0")" && pwd)}"
R="${CB_ROOT:-}"
ADDR="${CB_USB_ADDR:-169.254.77.2/16}"

CFG="$R/boot/firmware/config.txt"
[ -f "$CFG" ] || CFG="$R/boot/config.txt"
if [ -f "$CFG" ] && ! grep -q 'cloudbreak-usbnet' "$CFG"; then
  [ -f "$CFG.cloudbreak-usbnet.bak" ] || cp "$CFG" "$CFG.cloudbreak-usbnet.bak"
  printf '\n[pi02]\n# cloudbreak-usbnet: the USB data port is a network gadget to the laptop (usb0 = %s)\ndtoverlay=dwc2,dr_mode=peripheral\n[all]\n' "${ADDR%/*}" >>"$CFG"
  echo "config.txt: added [pi02] dtoverlay=dwc2,dr_mode=peripheral"
fi

mkdir -p "$R/usr/local/sbin" "$R/etc/systemd/system/multi-user.target.wants" \
         "$R/etc/systemd/system/getty.target.wants" "$R/etc/NetworkManager/system-connections"
sed 's/\r$//' "$S/usb_gadget.sh" >"$R/usr/local/sbin/cloudbreak-usb-gadget"
chmod 755 "$R/usr/local/sbin/cloudbreak-usb-gadget"
sed 's/\r$//' "$S/systemd/cloudbreak-usbgadget.service" >"$R/etc/systemd/system/cloudbreak-usbgadget.service"
chmod 644 "$R/etc/systemd/system/cloudbreak-usbgadget.service"
# enable by symlink: works whether or not systemd is fully up (first-run boots into kernel-command-line.target)
ln -sf /etc/systemd/system/cloudbreak-usbgadget.service \
       "$R/etc/systemd/system/multi-user.target.wants/cloudbreak-usbgadget.service"
GETTY=/lib/systemd/system/serial-getty@.service
[ -e "$R$GETTY" ] || GETTY=/usr/lib/systemd/system/serial-getty@.service
ln -sf "$GETTY" "$R/etc/systemd/system/getty.target.wants/serial-getty@ttyGS0.service"
echo "installed cloudbreak-usbgadget.service and serial-getty@ttyGS0"

# NetworkManager's stock 85-nm-unmanaged.rules leaves USB gadget interfaces (DEVTYPE=gadget) unmanaged, so the
# profile below would never be applied; hand usb0 back to it.
mkdir -p "$R/etc/udev/rules.d"
UDEV="$R/etc/udev/rules.d/90-cloudbreak-usb0-managed.rules"
printf '# cloudbreak-usbnet: let NetworkManager apply cloudbreak-usb0 to the USB gadget interface\nSUBSYSTEM=="net", ACTION=="add|change", KERNEL=="usb0", ENV{NM_UNMANAGED}="0"\n' >"$UDEV"
if [ -z "$R" ] && [ -e /sys/class/net/usb0 ] && command -v nmcli >/dev/null; then
  udevadm control --reload 2>/dev/null || true
  udevadm trigger --action=change /sys/class/net/usb0 2>/dev/null || true
  nmcli device set usb0 managed yes 2>/dev/null || true
fi

NM="$R/etc/NetworkManager/system-connections/cloudbreak-usb0.nmconnection"
if [ ! -f "$NM" ]; then
  UUID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c 'import uuid; print(uuid.uuid4())')
  cat >"$NM" <<EOF
[connection]
id=cloudbreak-usb0
uuid=$UUID
type=ethernet
interface-name=usb0
autoconnect=true
autoconnect-priority=100

[ethernet]

[ipv4]
method=manual
address1=$ADDR
never-default=true

[ipv6]
addr-gen-mode=default
method=link-local

[proxy]
EOF
  chmod 600 "$NM"
  echo "NetworkManager: cloudbreak-usb0 = $ADDR on usb0"
fi
if [ -z "$R" ] && command -v nmcli >/dev/null && systemctl is-active -q NetworkManager 2>/dev/null; then
  nmcli connection reload || true
fi
if [ -z "$R" ] && [ "$(ps -o comm= 1 2>/dev/null)" = systemd ]; then
  systemctl daemon-reload || true
fi
echo "usbnet_install: done (reboot for the config.txt change)"
