### Cloudbreak

## Hardware

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
                                          agent (local JEV-9B yes/no)  ─► proposals only  5765 QGC / sim pilot
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

The **agent** only proposes; it cannot approve or command anything. It asks a local, free yes/no decision model (JEV-9B, open weights, Apache-2.0) one question per feasible candidate and ranks them by P(yes); the explanation stays the deterministic template. Without the model or a GPU it falls back to the template alone.

**Landing pattern and fallback.** Governed landings fly a one-sided circuit: the hold and descent circle sits beside final and is tangent to it, the last look runs along the centreline, and turns go one known way via a downwind leg. Every turn is sized from the radius the aircraft actually flies (`turn_radius_m`, measured at gate F1). Below the decision point the governor enforces a stabilized-approach gate: off the centreline, off heading or off the glide path means an automatic go-around. After two unstable approaches, or when no site is feasible, the pilot lands manually.

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
.venv\Scripts\python -m cloudbreak.ground.agent.agent    # optional: JEV-9B yes/no ranking (--backend ollama for qwen3:4b)
```

1. Open http://127.0.0.1:8700 and click **survey →** on a nomination.
2. Approve it on http://127.0.0.1:8710 with the code from the governor window and `FLY xxxx`, then press **Execute**.
3. After enough coverage, select a feasible candidate and click **Request approval**.
4. Approve with `LAND xxxx` and press **Execute**. The plane flies to the hold.
5. Press **Commit** once the last look has at least 3 views.
6. Optional: **Inject person on strip** shows the automatic go-around.

All synthetic inputs are watermarked and labelled SYNTHETIC or ORACLE.

## JEV agent model (optional, free, local)

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[jev]"
.venv\Scripts\python -c "from huggingface_hub import snapshot_download; from cloudbreak.ground.agent.jev import NEEDED, REPO; snapshot_download(REPO, allow_patterns=NEEDED, local_dir=r'C:\cb-data\models\JEV-9B')"   # ~18 GB
.venv\Scripts\python scripts\jev_check.py      # sanity, ranking, speed, memory
```

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

The same SD card later moves to the Pi Zero 2 W. Swap the camera ribbon for the 22-pin Zero cable, and set the Zero's Wi-Fi to the field hotspot. The 40-pin header is the same, so the FC wiring (pins 6/8/10) and `/dev/serial0` (Bluetooth is disabled in `config.txt`) carry over unchanged. On the field, tell the laptop tools where the Zero is:

```powershell
$env:CLOUDBREAK_PI_HOST = "192.168.137.x"     # the Zero's Wi-Fi address (bench default: 169.254.77.2 over ethernet)
```

On the bench, the Zero talks to the laptop over a cable in its USB **data** port (not PWR IN). It shows up in Windows as an RNDIS network adapter plus a COM port, using Windows' own drivers, and keeps the bench address `169.254.77.2`. A card that has never had this set up is prepared in the laptop's card reader, because the Zero can't be reached until it is:

```powershell
.venv\Scripts\python scripts\sd_usbnet.py            # writes a one-shot first run to the boot partition
.venv\Scripts\python scripts\sd_usbnet.py --status   # after the Zero has booted it: shows firstrun.log
```

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

## Operating the FC from the laptop (Mission Planner + the signing proxy)

The FC signs every frame it sends, USB included, so a ground station without the key (Mission Planner) discards all of it. Mission Planner can't hold our key either: its signing dialog makes a key from a passphrase. `scripts/gcs_proxy.py` holds the key instead:
- FC → ground station: it checks each frame's signature and strips it.
- Ground station → FC: it signs each frame.
- It never forwards SETUP_SIGNING, so no ground station can change or clear the key.

It listens on 127.0.0.1 only and logs every parameter write, command and mode change to `C:\cb-data\proxy\`.

```powershell
scripts\mission_planner_signed.bat                                  # proxy (FC on USB, found by itself) + Mission Planner
.venv\Scripts\python scripts\gcs_proxy.py                           # proxy only; --fc COM5 or --fc tcp:<pi>:14560
.venv\Scripts\python scripts\gcs_proxy.py --read-only               # watching only: nothing that changes the FC is sent
```

In Mission Planner, choose **UDP** in the connection box at the top right, then **Connect**, port **14550**. Don't pick the FC's COM port there, because the proxy holds it. Repo scripts use the proxy's TCP port: `--port tcp:127.0.0.1:5770` (`fc_setup_usb.py` also needs `--no-signing` this way; the key is already on the FC).

Bench checks and calibrations without Mission Planner (`scripts/fc_bench.py`; through the proxy if it's running, else straight on USB). Each run writes a record to `C:\cb-data\fc\bench_*.json`:

```powershell
.venv\Scripts\python scripts\fc_bench.py status     # pre-arm failures, GPS, compass, RC, SD card, output map
.venv\Scripts\python scripts\fc_bench.py outputs    # output map read-back for P1 (flags throttle not at minimum, off-centre trims)
.venv\Scripts\python scripts\fc_bench.py rc         # live RC channels (bind check)
.venv\Scripts\python scripts\fc_bench.py logs       # microSD card check + DataFlash log list
.venv\Scripts\python scripts\fc_bench.py accel      # 6-position accel calibration; detects each position by itself
.venv\Scripts\python scripts\fc_bench.py radio      # RCn_MIN/MAX/TRIM from stick sweeps (needs the receiver bound)
.venv\Scripts\python scripts\fc_bench.py compass --accept   # outdoors, installed in the airframe
.venv\Scripts\python scripts\fc_bench.py level      # installed, at flying attitude
.venv\Scripts\python scripts\fc_bench.py servos     # live sticks -> surfaces (+ FC tilt): direction checks in MANUAL and FBWA
.venv\Scripts\python scripts\fc_bench.py mode MANUAL   # / reverse 6: mode from the laptop, flip SERVOn_REVERSED (disarmed only)
```

**Check directions in FBWA too, not only MANUAL.** If the pitch input (RC2) and the elevator servo are both reversed, MANUAL looks right while FBWA corrects pitch the wrong way. The Tutor needs RC2_REVERSED 1 and SERVO5_REVERSED 1 (both in `config/fc_params.toml`).

Bench motor run (prop off, P1-approved; STATUS.md section 2 #6 (d)): `scripts\bench_motor_run.py` relaxes the fence and the GPS/compass/AHRS pre-arm checks for one run, with throttle capped at 40 %. It disarms on any mode change, RC loss or timeout, then restores and re-audits everything. `--restore` recovers from a crash.

**After changing any SERVOn_FUNCTION, reboot the FC and run `fc_bench.py outputs` before plugging anything in.** On 2026-11-07, S1 kept putting out 1500 µs (aileron centre) after it became the throttle output, and dropped to the 1100 µs minimum only after a reboot.

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
- `cloudbreak/ground/agent/`: advisory agent: JEV-9B yes/no ranker (`jev.py`), optional Ollama backend, template fallback.
- `cloudbreak/ground/autoland/`: SITL Bayesian optimisation and touchdown dispersion.
- `cloudbreak/{heartbeat,capture,landability,planner,governor}.py`: the initial skeleton modules, with tests in `tests/test_landability.py` and `tests/test_governor_skeleton.py`. `heartbeat.py` is the listen-only link check.
- `sim/`: SITL scripts, synthetic camera, sim pilot.
- `config/`: site, targets, aircraft, flight gates.
- `STATUS.md`: master team status (gate board, blockers, decisions, remaining plan).
- `docs/updates/`: timestamped personal updates (P1–P4) and the update template.
- `docs/hardware/`: wiring diagram + connection tables (`WIRING.md`, `wiring.svg`, generator `wiring_svg.py`) and FC configuration backups (`fc/`, INAV 8.0.1 pre-ArduPlane).
- `scripts/`: Pi deploy, FC setup through the Pi (`fc_params_pi.py`) or over USB (`fc_setup_usb.py`), and the HITL bench test.
- `tools/servo_bench/`: servo bench tester (browser page + Arduino UNO Q sketch) for centring and checking one servo at a time on D9 without the FC.

Data, keys, weights and sessions live in `C:\cb-data`, never in git.

## References

- [ArduPlane docs](https://ardupilot.org/plane/docs/)
- [CoreWing F405 Wing V2 on ArduPilot](https://ardupilot.org/plane/docs/common-CoreWingF405WingV2.html)
- [Raspberry Pi camera software](https://www.raspberrypi.com/documentation/computers/camera_software.html)
- [ExpressLRS docs](https://www.expresslrs.org/)
- [pymavlink](https://github.com/ArduPilot/pymavlink)
