#!/usr/bin/env bash
# One-time Pi setup (works on the Pi 3 dev board and, after the SD card moves, on the Pi Zero 2 W).
#   sudo bash /opt/cloudbreak/src/cloudbreak/air/setup_pi.sh
# - apt deps (picamera2, opencv, numpy, simplejpeg) + venv with system site packages + pymavlink
# - /etc/cloudbreak/air.toml (kept if present)
# - UART: PL011 on /dev/serial0 (dtoverlay=disable-bt), serial login console OFF, UART hardware ON
# - Zero 2 W USB network link to the laptop (usbnet_install.sh: RNDIS gadget, usb0 = 169.254.77.2/16)
# - flight trim (slim_pi.sh: 1-Wire overlay off, cloud-init off, unused services disabled; reversible)
# - systemd units (memory-capped for the Zero's 512 MB); a reboot is needed for the UART change
set -euo pipefail
CB_USER="${SUDO_USER:-$(id -un)}"
SRC=/opt/cloudbreak/src
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y python3-picamera2 python3-opencv python3-numpy python3-venv python3-pip python3-simplejpeg rsync

python3 -m venv --system-site-packages /opt/cloudbreak/venv
/opt/cloudbreak/venv/bin/pip install -q pymavlink

mkdir -p /etc/cloudbreak
if [ ! -f /etc/cloudbreak/air.toml ]; then
  sed "s#@USER@#${CB_USER}#g" "$SRC/cloudbreak/air/air.example.toml" > /etc/cloudbreak/air.toml
fi
mkdir -p "/home/${CB_USER}/sessions"
chown "${CB_USER}:" "/home/${CB_USER}/sessions"
usermod -aG dialout,video "${CB_USER}" || true

CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
cp -n "$CFG" "${CFG}.cloudbreak.bak" || true
grep -q '^enable_uart=1' "$CFG" || echo 'enable_uart=1' >> "$CFG"
grep -q '^dtoverlay=disable-bt' "$CFG" || echo 'dtoverlay=disable-bt' >> "$CFG"
grep -q '^camera_auto_detect=1' "$CFG" || echo 'camera_auto_detect=1' >> "$CFG"
systemctl disable --now hciuart 2>/dev/null || true
if command -v raspi-config >/dev/null; then
  raspi-config nonint do_serial_cons 1 || true   # 1 = disable login shell on serial
  raspi-config nonint do_serial_hw 0 || true     # 0 = enable serial hardware
fi

# Zero 2 W: the USB data port as a network link to the laptop (usb0 = 169.254.77.2); does nothing on a Pi 3
bash "$SRC/cloudbreak/air/usbnet_install.sh" "$SRC/cloudbreak/air"
# Flight trim for 512 MB: 1-Wire overlay, cloud-init, old dnsmasq, printing/modem/desktop audio (undo: --undo)
bash "$SRC/cloudbreak/air/slim_pi.sh"

for unit in mavbridge capture frameserver; do
  sed "s#@USER@#${CB_USER}#g" "$SRC/cloudbreak/air/systemd/cloudbreak-${unit}.service" \
    > "/etc/systemd/system/cloudbreak-${unit}.service"
done
systemctl daemon-reload
systemctl enable cloudbreak-mavbridge cloudbreak-capture cloudbreak-frameserver
echo "[setup_pi] done. Reboot to apply the UART change (sudo reboot)."
