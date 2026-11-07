# Electronics progress: power, ESC/motor, flight controller, radio, GPS

**Owner:** _TBD (electronics)_
**Last updated:** _awaiting update_
**Overall:** _awaiting update_

> **Repo state, pre-filled** from `docs/CHECKLIST.md` (`b36bcaa`) and the airframe update, so updates line up. The owner should correct it and fill in the rest. Status words are in [TEMPLATE.md](TEMPLATE.md).

## Repo state so far

| Item | State | Source |
|---|---|---|
| FC identity: CoreWing F405 Wing Mini V2, ArduPlane 4.7.2 | Done (passed) | CHECKLIST |
| FC parameter backup; Cloudbreak params + signing key applied | Done (applied) | CHECKLIST |
| FC → Pi UART4 at 230400 (after rewiring the TELEM pigtail) | Done (passed) | CHECKLIST |
| Wiring-incident follow-up: USB dry run, Vcc = 0, TELEM pin 6 disconnected | In progress | CHECKLIST |
| ESC soldered (motor side + battery lead) | In progress | [airframe.md](airframe.md) |
| Motor spin test, prop off; direction correct | Not started | |
| Receiver (XR1 Nano) bound to the Pocket; CRSF into the FC | Not started ("waiting for RC") | CHECKLIST |
| Pocket switches: flight mode FBWA/AUTO/RTL, consent on RC7 | Not started | `docs/FLIGHT_CARDS.md` |
| 3D accel calibration; compass 1 healthy; GPS home | Not started (open pre-arm items) | CHECKLIST |
| Servos + ESC signal on FC outputs | | |
| Pi UBEC holds 5.1–5.2 V at the Pi | | CHECKLIST (under-voltage seen on the bench) |
| TX-off failsafe test (prop off), range check | Not started (F0) | `config/flight_gates.toml` |

## Summary

_Owner to fill in._

## Left to do

_Owner to fill in (order, dependencies)._

## Handoffs and interfaces

- **→ Airframe:** agree FC, receiver and GPS mounting positions (airframe step A2). Joint surface-setup session once the FC drives the servos (A4).
- **→ Onboard:** Pi power (UBEC) and the TELEM wiring into the Zero.

## Risks / watch items

_Owner to fill in._
