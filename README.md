# Cloudbreak

Cloudbreak is an RC plane (Flite Test Tutor, ArduPlane 4.7.2 on a CoreWing F405 Wing Mini V2). It finds a landing strip from its own downward camera plus free public geodata, explains the choice, and lands only after a human approves and a deterministic governor agrees. Built for HackRPI 2026.

**Status (7 Nov 2026).** The full cross-team picture (gates, blockers, decisions, remaining plan) is in [`STATUS.md`](STATUS.md).

- **Done and tested:** SITL, governor, planner, priors and core all work end to end. Unit tests pass. SITL behaviours are verified (see `docs/sitl_notes.md`).
- **Bench hardware:**
  - The Pi 3 camera, frame server and MAVLink bridge run on the bench.
  - The real FC streams signed MAVLink2 over UART4 (TELEM) at 230400 to the Pi, and on to the laptop.
  - The signed uplink passed the HITL bench test (`scripts/hitl_bench.py`). Signed commands work through the Pi; unsigned, wrong-key and disallowed commands are dropped at the Pi or ignored by the FC.
- **Airframe:** the Tutor is mechanically built (fuselage, wing, power pod, landing gear, servos linked). It hasn't been powered yet; the camera opening, avionics mounting, surface setup and CG are left. See `docs/updates/P2_2026-11-07_1721.md`.
- **Hardware commissioning (critical path):** the FC goes to the power marshal for power-board soldering (G1/G2), then radio, servos, GPS and the Pi on the UBEC (G3–G5). Output mapping must be fixed before the ESC goes on S1.
- **Not done:** no real flight yet. The plan is an F1 maiden at first light on Sunday 11/8, if F0 passes overnight and the field go/no-go is met (`STATUS.md` §5–6). Coding stops at 11:00; flying can continue. See `docs/CHECKLIST.md` for what is and isn't verified.
- **Wiring:** full diagram and connection tables in `docs/hardware/WIRING.md`.

## Hardware baseline

| Role | Part |
|---|---|
| Airframe | Flite Test Tutor, standard ~1055 mm wing, single tractor motor, 4 servos |
| Flight controller | CoreWing F405 Wing Mini V2 (banner: `CoreWingF405WMiniV2`), ArduPlane 4.7.2 |
| Pilot link | RadioMaster Pocket ELRS 2.4 GHz → XR1 Nano receiver (CRSF) |
| GPS / compass | RMRC SAM-M10Q + 5883 |
| Companion | Raspberry Pi Zero 2 W (developed on a Pi 3) on its own 5 V UBEC. MAVLink2 over the FC's TELEM port (UART4); wiring in `docs/CHECKLIST.md` |
| Camera | Raspberry Pi Camera Module 3 Standard (IMX708) |
| Battery | 3S 1300 mAh LiPo |

## How it fits together

```
Pi Zero 2 W (air)                      Laptop (Windows)                                  WSL2
 camera ─ capture.py ─ HTTP :8080 ◄─pull── core  (127.0.0.1:8700, UI)                    ArduPlane SITL
 FC UART ─ mavbridge.py ─ TCP :14561 ──► core  (read-only telemetry)                      5762 governor (signed)
                         TCP :14560 ◄──► governor (127.0.0.1:8710) ──signed MAVLink──►    5763 core (ro)
                                          agent (local LLM via Ollama) ─► proposals only  5765 QGC / sim pilot
```

**Core** fuses three inputs into a Dirichlet evidence grid (0.5 m, EPSG:32618):
- camera frames, projected onto the LiDAR DTM;
- priors (NYS 2024 ortho, USGS 3DEP LiDAR, OSM, FAA obstacles);
- wind (forecast + EKF3).

A cell needs at least 3 good views before it can count as safe. A strip needs two things:
- every cell's 5 % lower credible bound P(safe) ≥ 0.40;
- the strip mean of that bound ≥ 0.65.

Both thresholds are calibrated on SITL ground truth only, and must be redone on labelled real frames. Unknown is never safe.

The **planner** searches strips at every heading and scores them with explained terms. It checks the approach and missed-approach path against the LiDAR surface model.

The **governor** is the only process that writes to the aircraft:
- It rebuilds the mission itself and hashes it.
- A human approves it with a one-time code shown only in the governor console.
- It checks the target fingerprint, telemetry, EKF, battery, clearance, flight gates and parameters.
- It uploads the mission signed, reads it back and verifies the hash.
- It flies hold, then last look, then commit, then land. It aborts by itself if the site is invalidated.

The **agent** only proposes; it cannot approve or command anything.

## Ground rules

- The AI agent never controls actuators and never approves its own plans.
- The pilot's radio can always take over, independent of Wi-Fi or the Pi.
- Pre-arm checks stay on. Fix the specific failure instead of disabling checks.
- SITL and real-aircraft command paths stay clearly separated.
- Electronics booting is not flight readiness.

## Quick start (laptop)

```powershell
python -m venv .venv                                     # Python 3.11+ (or: uv venv --python 3.11 .venv)
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

## Run the SITL demo

```powershell
.\sim\sitl\run_sitl.ps1 -Speedup 1                       # WSL SITL at RPI '86 Field (window 1)
.venv\Scripts\python sim\sitl\setup_signing.py           # install SITL signing key (once per SITL start)
.venv\Scripts\python -m cloudbreak.ground.governor.governor --target sitl   # window 2: shows one-time codes
.venv\Scripts\python -m cloudbreak.ground.core.api --target sitl --source synthetic --perception oracle
.venv\Scripts\python sim\sim_pilot.py                    # SITL stand-in for the pilot (arming / mode switch)
.venv\Scripts\python -m cloudbreak.ground.agent.agent    # optional local LLM proposals (Ollama qwen3:4b)
```

1. Open http://127.0.0.1:8700 and click **survey →** on a nomination.
2. Approve it on http://127.0.0.1:8710 with the code from the governor window and `FLY xxxx`, then press **Execute**.
3. After enough coverage, select a feasible candidate and click **Request approval**.
4. Approve with `LAND xxxx` and press **Execute**. The plane flies to the hold.
5. Press **Commit** once the last look has at least 3 views.
6. Optional: **Inject person on strip** shows the automatic go-around.

All synthetic inputs are watermarked and labelled SYNTHETIC or ORACLE.

## Rebuild the priors

```powershell
.venv\Scripts\python -m cloudbreak.ground.core.priors.fetch      # ~0.3 GB into C:\cb-data\priors\raw
.venv\Scripts\python -m cloudbreak.ground.core.priors.build_layers
```

Set `CLOUDBREAK_SITE=schuyler`, or pass `--site schuyler`, for Schuyler Flatts.

## Pi (air side)

```bash
scripts/deploy_pi.sh <user>@<pi-ip> --setup     # once; then sudo reboot (UART change)
scripts/deploy_pi.sh <user>@<pi-ip>             # later updates
```

The same SD card later moves to the Pi Zero 2 W. Swap the camera ribbon for the 22-pin Zero cable, and set the Zero's Wi-Fi to the field hotspot.

## FC configuration (through the Pi, no USB)

Desired values are in `config/fc_params.toml`. Every command signs with the governor key, and writes only work while the FC is disarmed:

```powershell
.venv\Scripts\python scripts\fc_params_pi.py backup                       # full parameter backup (read-only)
.venv\Scripts\python scripts\fc_params_pi.py audit --site schuyler        # desired vs FC, incl. fence (read-only)
.venv\Scripts\python scripts\fc_params_pi.py apply --yes                  # set differing parameters
.venv\Scripts\python scripts\fc_params_pi.py fence --site schuyler --yes  # upload + verify polygon, then enable
.venv\Scripts\python scripts\hitl_bench.py --direct                       # re-verify the signed command path
```

The Pi forwards parameter writes only inside a 5-minute maintenance window, which the script opens over SSH and closes afterwards. Link and identity parameters (SERIAL4_*, MAV_SYSID, MAV_GCS_SYSID, ARMING_*) and the signing key can only be changed over USB (`scripts/fc_setup_usb.py`).

**Geofence:** each site's `[fence]` polygon is uploaded to the FC (breach → RTL). The planner and governor require every planned path point to be 20 m inside it. With the fence enabled, the FC refuses to arm outside the polygon, so upload the right site's fence before flying somewhere else.

The listen-only link check from the initial skeleton still works. On the Pi, stop `cloudbreak-mavbridge` first, because the UART can have only one reader:

```bash
python -m cloudbreak.heartbeat --device tcp:127.0.0.1:5760          # SITL
python -m cloudbreak.heartbeat --device /dev/serial0 --baud 230400  # Pi UART to the FC (SERIAL4_BAUD=230)
```

## Layout

- `cloudbreak/common/`: schemas, geodesy, MAVLink link and mission hash, mission builder, clearance, audit log, clock model.
- `cloudbreak/air/`: Pi services.
- `cloudbreak/ground/core/`: priors, geometry, mapping, planner, environment, API, UI.
- `cloudbreak/ground/governor/`: approval, checks, execution, approval page.
- `cloudbreak/ground/agent/`: local LLM agent and template fallback.
- `cloudbreak/ground/autoland/`: SITL Bayesian optimisation and touchdown dispersion.
- `cloudbreak/{heartbeat,capture,landability,planner,governor}.py`: the initial skeleton modules, with tests in `tests/test_landability.py` and `tests/test_governor_skeleton.py`. `heartbeat.py` is the listen-only link check.
- `sim/`: SITL scripts, synthetic camera, sim pilot.
- `config/`: site, targets, aircraft, flight gates.
- `STATUS.md`: master team status (gate board, blockers, decisions, remaining plan).
- `docs/updates/`: timestamped personal updates (P1–P4) and the update template.
- `docs/hardware/`: wiring diagram + connection tables (`WIRING.md`, `wiring.svg`, generator `wiring_svg.py`) and FC configuration backups (`fc/`, INAV 8.0.1 pre-ArduPlane).
- `scripts/`: Pi deploy, FC setup through the Pi (`fc_params_pi.py`) or over USB (`fc_setup_usb.py`), and the HITL bench test.

Data, keys, weights and sessions live in `C:\cb-data`, never in git.

## References

- [ArduPlane docs](https://ardupilot.org/plane/docs/)
- [CoreWing F405 Wing V2 on ArduPilot](https://ardupilot.org/plane/docs/common-CoreWingF405WingV2.html)
- [Raspberry Pi camera software](https://www.raspberrypi.com/documentation/computers/camera_software.html)
- [ExpressLRS docs](https://www.expresslrs.org/)
- [pymavlink](https://github.com/ArduPilot/pymavlink)
