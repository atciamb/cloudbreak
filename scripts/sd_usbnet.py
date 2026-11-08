"""Prepare the Pi's SD card (in the laptop's card reader) so the Pi Zero 2 W comes up as a USB network adapter.

    .venv\\Scripts\\python scripts\\sd_usbnet.py            # finds the Pi boot partition (bootfs) by itself
    .venv\\Scripts\\python scripts\\sd_usbnet.py --drive E:  # or name it
    .venv\\Scripts\\python scripts\\sd_usbnet.py --status    # only print firstrun.log from a card that has booted

Why: the Zero has no ethernet, and its Wi-Fi address on the campus network is unknown (no mDNS across it). Only
the FAT boot partition is writable from Windows, so this copies cloudbreak-usbnet/ there and adds a one-shot
`systemd.run=` to cmdline.txt. On the next boot the Pi runs usbnet_firstrun.sh once (it removes itself from
cmdline.txt first), installs the RNDIS + serial USB gadget and a NetworkManager profile (usb0 = 169.254.77.2/16),
and reboots. Then, with a cable in the Zero's USB data port: `ssh pidrone@169.254.77.2` (same as the Pi 3 bench).

Touches only cmdline.txt (one line, backed up to cmdline.txt.cloudbreak-usbnet.bak) and the new folder; config.txt
is changed on the Pi by usbnet_install.sh (also backed up there).
"""
from __future__ import annotations

import argparse
import shutil
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AIR = ROOT / "cloudbreak" / "air"
FOLDER = "cloudbreak-usbnet"
FILES = {"usb_gadget.sh": AIR / "usb_gadget.sh", "usbnet_install.sh": AIR / "usbnet_install.sh",
         "firstrun.sh": AIR / "usbnet_firstrun.sh",
         "systemd/cloudbreak-usbgadget.service": AIR / "systemd" / "cloudbreak-usbgadget.service"}
RUN_ARGS = (f"systemd.run=/boot/firmware/{FOLDER}/firstrun.sh systemd.run_success_action=reboot "
            "systemd.unit=kernel-command-line.target")


def is_bootfs(p: Path) -> bool:
    try:
        return (p / "cmdline.txt").is_file() and (p / "config.txt").is_file() and any(p.glob("start*.elf"))
    except OSError:
        return False


def find_bootfs() -> list[Path]:
    return [Path(f"{d}:\\") for d in string.ascii_uppercase if d not in "C" and is_bootfs(Path(f"{d}:\\"))]


def add_run_args(cmdline: str) -> str:
    """cmdline.txt is ONE line; append the one-shot args unless already there."""
    line = " ".join(cmdline.split())                  # also drops CR/LF and doubled spaces
    if "root=" not in line:
        raise ValueError("cmdline.txt has no root= (not a Raspberry Pi OS boot partition?)")
    if "systemd.run=" in line:
        if FOLDER in line:
            return line + "\n"
        raise ValueError("cmdline.txt already has a different systemd.run= (an unfinished Imager first run?)")
    return f"{line} {RUN_ARGS}\n"


def prepare(boot: Path) -> list[str]:
    notes = []
    if not (boot / "bcm2710-rpi-zero-2-w.dtb").exists():
        notes.append("warning: no bcm2710-rpi-zero-2-w.dtb on this card (the firmware may be too old for a Zero 2 W)")
    cmd = boot / "cmdline.txt"
    old = cmd.read_text(encoding="utf-8")
    new = add_run_args(old)
    dst = boot / FOLDER
    (dst / "systemd").mkdir(parents=True, exist_ok=True)
    for rel, src in FILES.items():                    # LF only: bash on the Pi rejects CRLF scripts
        text = src.read_text(encoding="utf-8").replace("\r\n", "\n")
        (dst / rel).write_bytes(text.encode("utf-8"))
    if new != old:
        bak = boot / "cmdline.txt.cloudbreak-usbnet.bak"
        if not bak.exists():
            shutil.copyfile(cmd, bak)
        cmd.write_bytes(new.encode("utf-8"))
    notes.append(f"copied {len(FILES)} files to {dst}")
    notes.append(f"cmdline.txt: {new.strip()}")
    return notes


def status(boot: Path) -> str:
    log = boot / FOLDER / "firstrun.log"
    cmd = (boot / "cmdline.txt").read_text(encoding="utf-8")
    pending = "systemd.run=" in cmd
    head = "first run still pending (the Pi has not booted this card yet)" if pending else "first run done"
    return head + "\n" + (log.read_text(encoding="utf-8", errors="replace") if log.exists() else "(no firstrun.log yet)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--drive", help="boot partition, e.g. E: (default: find it)")
    ap.add_argument("--status", action="store_true", help="only show firstrun.log")
    a = ap.parse_args()
    if a.drive:
        boot = Path(a.drive if a.drive.endswith(("\\", "/")) else a.drive + ("\\" if a.drive.endswith(":") else ""))
        if not is_bootfs(boot):
            print(f"{boot} is not a Raspberry Pi boot partition (needs cmdline.txt, config.txt, start*.elf)")
            return 1
    else:
        found = find_bootfs()
        if len(found) != 1:
            print("no Pi boot partition found; is the SD card in the reader?" if not found
                  else f"several Pi boot partitions: {found}; pass --drive")
            return 1
        boot = found[0]
    print(f"Pi boot partition: {boot}")
    if a.status:
        print(status(boot))
        return 0
    for n in prepare(boot):
        print(n)
    print("\nEject the card in Windows, put it back in the Zero, power it, and connect the Zero's USB *data* port "
          "to the laptop. The first boot reboots once by itself (allow ~3 min); then ssh pidrone@169.254.77.2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
