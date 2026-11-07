# Cloudbreak

HackRPI 2026 project: a small RC aircraft photographs the ground, a ground laptop turns the imagery into a conservative landability map, a planner ranks candidate landing strips, and an AI agent explains its pick. **A human approves the plan**, and a deterministic governor checks it before any mission command reaches the autopilot.

> **Status:** initial skeleton. No hardware commissioning, bench or flight test is recorded as passed in this repo yet.

## Pipeline

1. **Capture (aircraft):** Raspberry Pi Zero 2 W + Camera Module 3 records downward-looking frames and tags them with autopilot position/attitude over MAVLink.
2. **Map (ground):** frames become a landability grid: usable ground, obstacles, people, water, unknown. Unknown is never treated as safe.
3. **Plan (ground):** rank candidate strips and approach paths by geometry, obstacles, evidence and wind (when defensible).
4. **Explain (ground):** an AI agent inspects candidates and proposes one. It cannot command actuators or approve its own proposal.
5. **Approve + govern:** a human approves a specific plan; a deterministic governor checks the plan and aircraft/link state before allowing mission upload.
6. **Fly:** ArduPlane does flight control; the pilot keeps an independent radio takeover path. Everything is logged for replay.

**Required demo:** live bench camera + telemetry, plus a full human-approved, governor-checked landing sequence in ArduPlane SITL. Simulated or synthetic inputs are labeled. Real flight is optional.

## Hardware baseline

| Role | Part |
|---|---|
| Airframe | Flite Test Tutor, standard ~1055 mm wing, single tractor motor, 4 servos |
| Flight controller | CoreWing F405 Wing Mini (V2, pending board identification), ArduPlane |
| Pilot link | RadioMaster Pocket ELRS 2.4 GHz → XR1 Nano receiver (CRSF) |
| GPS / compass | RMRC SAM-M10Q + 5883 |
| Companion | Raspberry Pi Zero 2 W on its own 5 V UBEC, MAVLink2 over UART |
| Camera | Raspberry Pi Camera Module 3 Standard (IMX708) |
| Battery | 3S 1300 mAh LiPo |

## Repo layout

```
cloudbreak/          Python package (ground + companion code lives here)
  heartbeat.py       read-only MAVLink link check (Pi↔FC or SITL)
requirements.txt     Python dependencies
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# SITL (ArduPlane's default TCP port)
python -m cloudbreak.heartbeat --device tcp:127.0.0.1:5760

# On the Pi, over the UART to the flight controller
python -m cloudbreak.heartbeat --device /dev/serial0 --baud 115200
```

The heartbeat check only listens; it never sends commands.

## Ground rules

- The AI agent never controls actuators and never approves its own plans.
- The pilot's radio can always take over, independent of Wi-Fi or the Pi.
- Pre-arm checks stay on. Fix the specific failure instead of disabling checks.
- SITL and real-aircraft command paths stay clearly separated.
- Electronics booting is not flight readiness.

## References

- [ArduPlane docs](https://ardupilot.org/plane/docs/)
- [CoreWing F405 Wing V2 on ArduPilot](https://ardupilot.org/plane/docs/common-CoreWingF405WingV2.html)
- [Raspberry Pi camera software](https://www.raspberrypi.com/documentation/computers/camera_software.html)
- [ExpressLRS docs](https://www.expresslrs.org/)
- [pymavlink](https://github.com/ArduPilot/pymavlink)
