#!/bin/bash
# Trim the Pi OS image for flight on the Pi Zero 2 W (512 MB). Idempotent; reversible with --undo.
#   sudo bash slim_pi.sh            # apply, then reboot
#   sudo bash slim_pi.sh --undo     # restore what this script changed, then reboot
# Measured on the Zero 2026-11-07 before trimming:
#   - dtoverlay=w1-gpio: the 1-Wire bus master kept ~70 % of a core busy finding ghost devices on the floating
#     GPIO4. Nothing in Cloudbreak uses 1-Wire.
#   - cloud-init (first-boot customisation): its config stage hung every boot (DataSourceNone), so boot never finished.
#   - dnsmasq.service from an old hotspot attempt: a DHCP server for 192.168.50.x on wlan0 while wlan0 is a campus
#     Wi-Fi client, holding ports 53/67 that NetworkManager's own "shared" hotspot (PiDrone profile) needs.
#   - Printing, modem, Bluetooth, NFS and test services; desktop audio and Raspberry Pi Connect in the user session.
#     ModemManager also probes serial ports, which could include the FC UART.
# Kept: ssh, NetworkManager, avahi (raspberrypi.local on the USB link), timesyncd, cron, the cloudbreak-* units.
# What was actually changed is recorded in /etc/cloudbreak/slim-state, which --undo reads.
set -eu
STATE=/etc/cloudbreak/slim-state
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
SYSTEM_UNITS="dnsmasq.service cups.service cups.socket cups.path cups-browsed.service ModemManager.service
  bluetooth.service rpcbind.service rpcbind.socket nfs-blkmap.service udisks2.service accounts-daemon.service
  lightdm.service glamor-test.service rp1-test.service"
USER_UNITS="pipewire.socket pipewire.service pipewire-pulse.socket pipewire-pulse.service wireplumber.service
  filter-chain.service mpris-proxy.service pulseaudio.socket pulseaudio.service rpi-connect.service
  rpi-connect-wayvnc.service"

if [ "${1:-}" = "--undo" ]; then
  [ -f "$STATE" ] || { echo "slim_pi: nothing to undo ($STATE missing)"; exit 0; }
  while read -r kind name; do
    case "$kind" in
      system) systemctl enable "$name" 2>/dev/null && echo "re-enabled $name" ;;
      user) systemctl --global unmask "$name" 2>/dev/null && echo "unmasked user $name" ;;
      w1) sed -i 's|^#dtoverlay=w1-gpio  # cloudbreak-slim.*|dtoverlay=w1-gpio|' "$CFG" && echo "restored dtoverlay=w1-gpio" ;;
      cloudinit) rm -f /etc/cloud/cloud-init.disabled && echo "re-enabled cloud-init" ;;
    esac
  done <"$STATE"
  rm -f "$STATE"
  echo "slim_pi: undone; reboot to apply"
  exit 0
fi

mkdir -p /etc/cloudbreak
touch "$STATE"
record() { grep -qx "$1 $2" "$STATE" || echo "$1 $2" >>"$STATE"; }

if grep -q '^dtoverlay=w1-gpio' "$CFG"; then
  [ -f "$CFG.cloudbreak-slim.bak" ] || cp "$CFG" "$CFG.cloudbreak-slim.bak"
  sed -i 's|^dtoverlay=w1-gpio.*|#dtoverlay=w1-gpio  # cloudbreak-slim: 1-Wire unused, its bus scan cost ~70 % CPU|' "$CFG"
  record w1 overlay
  echo "config.txt: dtoverlay=w1-gpio commented out"
fi

if [ -d /etc/cloud ] && [ ! -e /etc/cloud/cloud-init.disabled ]; then
  touch /etc/cloud/cloud-init.disabled
  record cloudinit disabled
  echo "cloud-init disabled (/etc/cloud/cloud-init.disabled)"
fi

for u in $SYSTEM_UNITS; do
  st=$(systemctl is-enabled "$u" 2>/dev/null || true)
  case "$st" in
    enabled|enabled-runtime|indirect)
      systemctl disable --now "$u" >/dev/null 2>&1 || true
      record system "$u"
      echo "disabled $u" ;;
  esac
done

for u in $USER_UNITS; do
  [ -e "/etc/systemd/user/$u" ] && [ "$(readlink "/etc/systemd/user/$u")" = /dev/null ] && continue
  if [ -e "/usr/lib/systemd/user/$u" ] || [ -e "/lib/systemd/user/$u" ]; then
    systemctl --global mask "$u" >/dev/null 2>&1 && record user "$u" && echo "masked user $u"
  fi
done
echo "slim_pi: done; reboot to apply (state in $STATE)"
