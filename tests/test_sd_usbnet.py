"""The laptop-side SD card prep for the Zero's USB network link: one-line cmdline.txt, LF scripts, idempotent."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("sd_usbnet", Path(__file__).resolve().parents[1] / "scripts" / "sd_usbnet.py")
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)

CMDLINE = "console=serial0,115200 console=tty1 root=PARTUUID=0a1b2c3d-02 rootfstype=ext4 fsck.repair=yes rootwait\n"


def fake_boot(tmp_path: Path, cmdline: str = CMDLINE) -> Path:
    (tmp_path / "cmdline.txt").write_bytes(cmdline.encode())
    (tmp_path / "config.txt").write_text("[all]\nenable_uart=1\n")
    (tmp_path / "start4.elf").write_bytes(b"")
    (tmp_path / "bcm2710-rpi-zero-2-w.dtb").write_bytes(b"")
    return tmp_path


def test_prepare_appends_one_shot_run_and_copies_lf_scripts(tmp_path):
    boot = fake_boot(tmp_path)
    assert sd.is_bootfs(boot)
    sd.prepare(boot)
    cmd = (boot / "cmdline.txt").read_bytes().decode()
    assert cmd.count("\n") == 1 and cmd.endswith("rootwait " + sd.RUN_ARGS + "\n")
    assert (boot / "cmdline.txt.cloudbreak-usbnet.bak").read_bytes().decode() == CMDLINE
    for rel in sd.FILES:
        assert b"\r" not in (boot / sd.FOLDER / rel).read_bytes(), rel
    assert sd.status(boot).startswith("first run still pending")


def test_prepare_is_idempotent(tmp_path):
    boot = fake_boot(tmp_path)
    sd.prepare(boot)
    once = (boot / "cmdline.txt").read_bytes()
    sd.prepare(boot)
    assert (boot / "cmdline.txt").read_bytes() == once
    assert (boot / "cmdline.txt.cloudbreak-usbnet.bak").read_bytes().decode() == CMDLINE


def test_refuses_foreign_first_run_and_non_pi_cmdline(tmp_path):
    with pytest.raises(ValueError):
        sd.add_run_args(CMDLINE.strip() + " systemd.run=/boot/firstrun.sh")
    with pytest.raises(ValueError):
        sd.add_run_args("quiet splash")


def test_crlf_cmdline_becomes_one_lf_line():
    out = sd.add_run_args(CMDLINE.replace("\n", "\r\n"))
    assert "\r" not in out and out.count("\n") == 1


def test_firstrun_removes_exactly_the_args_it_was_given():
    """usbnet_firstrun.sh's sed must strip every token RUN_ARGS adds (else the Pi would boot-loop into it)."""
    import re
    src = (Path(sd.AIR) / "usbnet_firstrun.sh").read_text()
    line = sd.add_run_args(CMDLINE).strip()
    pats = re.findall(r"-e 's\|(.*?)\|\|g'", src)
    assert len(pats) == 3
    for pat in pats:                                   # these sed BREs read the same as Python regexes
        line = re.sub(pat, "", line)
    assert line == CMDLINE.strip()
