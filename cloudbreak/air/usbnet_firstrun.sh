#!/bin/bash
# Run ONCE by systemd at boot: scripts/sd_usbnet.py (on the laptop) copied this folder to the SD card's boot
# partition and added "systemd.run=<this> systemd.run_success_action=reboot systemd.unit=kernel-command-line.target"
# to cmdline.txt. It first takes itself back off cmdline.txt (so a failure can never boot-loop), installs the USB
# network link, logs to firstrun.log next to it (readable from Windows), and exits 0; systemd then reboots normally.
set +e
D="$(cd "$(dirname "$0")" && pwd)"
CMD=/boot/firmware/cmdline.txt
[ -f "$CMD" ] || CMD=/boot/cmdline.txt
exec >>"$D/firstrun.log" 2>&1
echo "== $(date -Is) cloudbreak usbnet first run on $(tr -d '\0' </proc/device-tree/model 2>/dev/null)"
sed -i -e 's| systemd\.run=[^ ]*||g' -e 's| systemd\.run_success_action=[^ ]*||g' \
       -e 's| systemd\.unit=kernel-command-line\.target||g' "$CMD"
echo "cmdline.txt now: $(cat "$CMD")"
bash "$D/usbnet_install.sh" "$D"
echo "usbnet_install exit $?"
echo "hostname $(hostname); memory $(awk '/MemTotal/ {print $2" kB"}' /proc/meminfo)"
echo "root fs: $(findmnt -no SOURCE,OPTIONS / 2>/dev/null)"
sync
exit 0
