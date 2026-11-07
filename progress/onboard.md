# Onboard progress: Raspberry Pi + Camera Module 3 (air services)

**Owner:** _TBD (Pi + camera)_
**Last updated:** _awaiting update_
**Overall:** _awaiting update_

> **Repo state, pre-filled** from `docs/CHECKLIST.md` (`b36bcaa`) so updates line up. The owner should correct it and fill in the rest. Status words are in [TEMPLATE.md](TEMPLATE.md).

## Repo state so far

| Item | State | Source |
|---|---|---|
| Pi 3 bench setup: OS, SSH key, `setup_pi.sh` (PL011 UART, console off, 3 services) | Done (passed) | CHECKLIST |
| Camera frame saved with metadata (IMX708, binned 2304×1296) | Done (passed) | CHECKLIST |
| Frame server pull from the laptop | Done (passed) | CHECKLIST |
| Bridge against SITL; frames geotagged with pose | Done (passed) | CHECKLIST |
| Bridge on the real FC (`/dev/serial0`, 230400) | Done (set; FC→Pi passed) | CHECKLIST |
| Pi → FC direction (signed uplink, HITL) | Not started | CHECKLIST |
| `SensorTimestamp` vs `CLOCK_BOOTTIME` check | Not started (proposed) | CHECKLIST |
| Move to the Pi Zero 2 W: SD card, **22-pin Zero camera cable**, field-hotspot Wi-Fi | Not started | README |
| Zero memory headroom (services that could be disabled are listed in the session log) | | `docs/SESSION_LOG.md` |

## Summary

_Owner to fill in._

## Left to do

_Owner to fill in (order, dependencies)._

## Handoffs and interfaces

- **→ Airframe:** do we have the Zero camera cable, and what length? It decides where the Pi sits relative to the camera opening (airframe step A1).
- **→ Electronics:** UBEC voltage at the Pi; TELEM wiring with pin 6 left disconnected.
- **→ Ground AI:** frame and metadata format; the Pi session from F1 goes to `sysid.py`.

## Risks / watch items

_Owner to fill in._
