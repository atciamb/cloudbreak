# Cloudbreak live checklist

Legend: **passed** means evidence is recorded here. *Proposed* means it is written or planned but not yet run on hardware. Nothing becomes "passed" without a result.

## Software (laptop / SITL)

| Item | Status | Evidence |
|---|---|---|
| Unit tests | **passed** | `pytest`: 43 passed (uplink allowlist, mission hash round-trip, clock fit, governor refusal matrix, approvals, agent isolation) |
| ArduPlane 4.7.2 SITL build (WSL) | **passed** | `docs/sitl_notes.md` |
| SITL signing, read-back hash, hold, GCS failsafe→RTL, commit, DO_GO_AROUND, throttle abort, link-loss-after-commit lands | **passed** | `C:\cb-data\sitl_verify\verify_20261107T125818.json` |
| Priors: NYS 2024 ortho + CIR, 3DEP DEM, 3DEP LiDAR (EPT 2022 + 2018), OSM, FAA DOF, Open-Meteo | **passed** | `C:\cb-data\priors\layers\manifest.json` |
| Governor refuses a survey path with unknown obstacle height | **passed** | governor console, session demo1 (before the LiDAR hole fill) |
| Governor refuses execution at SITL battery < 30 % | **passed** | `C:\cb-data\sessions\demo1\audit_governor.jsonl` (`execute_refused`) |
| Survey approval → signed upload → read-back → AUTO survey in SITL | **passed** | `audit_governor.jsonl`, `executed` events |
| Evidence grid fills from synthetic frames (oracle perception) | **passed** | core UI; 2 passes give ~3,350 safe cells |
| End-to-end SITL landing via governor | **passed (flow)**; **accuracy not acceptable yet** | Session `demo2`, audit chain verified. Interleaved survey → grid → candidate C01a (Anderson, hdg 105°) → OTP approval → 18 checks → signed upload + read-back → hold → last-look leg (3 views) → commit (16 checks) → AUTO land. Rest point **+71 m past the aim point** (strip ends at +36 m), 4.6 m off centreline. SITL plane max glide ~6 % vs 12 % approach, plus long SITL rollout. Needs real-Tutor sysid and BO before F3 |
| Governor refuses a wrong one-time code (and counts down tries) | **passed** | `approval_refused` in `C:\cb-data\sessions\demo2\audit_governor.jsonl` |
| Local LLM agent (Ollama qwen3:4b) | **passed** (runs, proposals validated) | agent log: `no_safe_site` in ~2 s per call; output schema-checked; tests forbid MAVLink/governor imports |
| Autoland BO (SITL, CVaR over randomised wind/turbulence/baro drift/GPS noise) | **ran** 24 trials × 3 conditions | best tail cost (CVaR) 2.83 vs hand-set start 6.23 → `C:\cb-data\autoland\learned_landing.parm`. Not yet validated on held-out conditions |
| System ID from a DataFlash log | **passed** on a SITL log | SITL generic plane: idle glide 16:1, so max ~6 % glide. Explains its float on 12 % approaches; the Tutor's real log will set this |
| Safety threshold calibration (SITL ground truth, split-conformal, α = 1 %) | **passed** (synthetic only) | τ_cell = 0.395: 0.99 % of hazard cells pass, 91.6 % of safe cells pass → `p_safe_cell_min` 0.40, strip mean 0.65. **Must be redone on labelled real frames before flight** |
| Real-image segmenter (VDD YOLO26s-sem + VisDrone YOLO11s) | **passed** on a real ortho crop | 74 ms per 1152×648 on GPU; buildings, roads, vegetation and cars correct. **Fails on synthetic upsampled renders** (calls grass water), so oracle perception is used in SITL |

## Site findings (from data, not flights)

- **Schuyler Flatts Cultural Park** (`config/site_schuyler.toml`, priors in `C:\cb-data\priors\sites\schuyler`):
  - Airspace: inside **KALB Class C** (SFC–4300 ft MSL). FAA UAS Facility Map ceiling **400 ft**, LAANC enabled (107 and 44809). A **LAANC authorization is needed before every flight**, plus Remote ID.
  - Data: NYS 2024 ortho; LiDAR 2018 FEMA (10.6 M pts) + 2016 Columbia-Rensselaer (14.1 M pts); OSM shows 4 power lines and 38 poles/towers in the 2 km box; 6 FAA obstacles.
  - Terrain: a large open meadow on the Hudson floodplain (DTM 1.5–15 m). 110–220 m open length, with scattered single trees in the meadow; creek and I-787 on the east side.
  - What-if planner run (oracle grid): **2 feasible approaches, landing heading 0° and 15° at 42.7064, −73.7100, +2 m clearance**. Southbound approaches miss clearance by 3–11 m.

- **'86 Field:** every approach geometry tried (3,888 combinations) fails LiDAR clearance. The best still misses by 4.9 m over the buildings to the NW. It is not a viable autoland site for this airframe with these margins.
- **Anderson Field:** 110 feasible combinations. The best has landing heading about 100° (toward ESE), approach from 20 m on a 12 % glide, and a 15 % missed-approach climb, with +2 m margin. A 12 % glide is steeper than ArduPilot's "start at ≤10 %" advice, so it must be validated (BO, then gate F3).

## Hardware (bench), per the handoff stages

| Item | Status |
|---|---|
| Pi 3 reachable on ethernet | **passed**: `raspberrypi.local` (IPv6 link-local) plus a static `169.254.77.2/16` on eth0 (laptop is 169.254.133.166). ICS not needed; the Pi has internet over campus Wi-Fi (`rpi_wpa2`) |
| Pi OS identified, SSH key installed | **passed**: Raspberry Pi OS Trixie 64-bit, user `pidrone`, key `~/.ssh/cloudbreak_pi`, passwordless sudo |
| `setup_pi.sh` (picamera2, UART PL011, console off, services) | **passed**: `/dev/serial0 → ttyAMA0`, `console=tty1` only after reboot, 3 services active at boot |
| Camera frame saved with metadata | **passed**: IMX708 2304×1296 binned mode, 988 µs exposure, LensPosition 0, blur/clip metrics, ~10 fps processed, 1 frame/2 s kept without GPS |
| Frame server pull from the laptop | **passed**: 1152 px preview 22 KB / 9 ms, full 333 KB / 36 ms over ethernet |
| Bridge against SITL as stand-in FC (SSH reverse tunnel) | **passed**: 2,062 msgs, GPS fix, tlog written, frames geotagged with pose + `t_mid_fc_ms`. SITL clock runs ~1.3 % slow, so "drift" there is SITL, not the Pi |
| Pi power | **under-voltage seen** with the touch display attached (0x50000, "Undervoltage detected" when the camera started). **0x0 after the display was unplugged.** On the plane the UBEC must hold 5.1–5.2 V at the Pi |
| `SensorTimestamp` clock domain vs `CLOCK_BOOTTIME` | *proposed* |
| FC identity | **passed**: banner `ArduPlane V4.7.2 (fb773567)`, `CoreWingF405WMiniV2`, USB COM5 |
| FC full parameter backup | **passed**: 1137/1137 → `C:\cb-data\fc\params_backup_20261107T160030.parm` |
| FC params + signing via `scripts/fc_setup_usb.py` | **applied** (team go-ahead, keep 230400): MAV_SYSID 42, MAV_GCS_SYSID 245, LAND_ABORT_THR 1, FS_GCS_ENABL 3 (failsafe only in AUTO), FS_LONG_ACTN 1, FS_LONG_TIMEOUT 20, WP_RADIUS 20, MAV3 stream rates/options. A re-run dry run shows **0 remaining changes**. Signing key installed (`C:\cb-data\keys\mavlink_real.key`). Pre-change backup: `params_backup_20261107T161956.parm` |
| Signing enforced on SERIAL4 (unsigned commands ignored, signed accepted) | *proposed*: can only be tested through the Pi (USB is exempt by design), so it is part of the HITL bench test |
| Pi bridge on the real FC | **set** 2026-11-07: `/etc/cloudbreak/air.toml` uses `fc_url = "/dev/serial0"` and `fc_baud = 230400`. The bench config is kept as `air.toml.bench-HHMM` |
| FC pre-arm items seen in banner | open (hardware team): 3D accel calibration needed, compass 1 not healthy, waiting for RC, waiting for home |
| Pi ↔ FC UART4 link | **passed (FC → Pi direction)** 2026-11-07 17:14, after rewiring the TELEM pigtail. Before the rewire, pin 10 was held LOW and 0 bytes arrived. Afterwards: pin 10 toggles. `/dev/serial0` at 230400 gets 10,395 bytes in 2.5 s (252 MAVLink2 frames). Decoded: 540 msgs in 6 s, 528 signed, heartbeat sysid 42, MANUAL. Bridge → laptop over TCP :14561 gives 539 msgs in 6 s, after fixing a bridge crash on the first TCP client. Pi → FC direction is not tested yet (part of HITL) |
| FC settings after the wiring incident | **partly verified**: sysid 42 and signing are confirmed over the UART. The full USB dry run is pending, because COM5 enumerates but won't open (Windows error 31). Unplug the USB for ~5 s to clear it. The FC reports no board voltage (POWER_STATUS Vcc = 0), so a 4V5 back-feed can't be ruled out from software. TELEM pin 6 must stay disconnected |
| HITL: signed upload/read-back through the Pi, unsigned ignored, props off | *proposed* |
| Airframe (Tutor) build | **built, nothing checked yet** (2026-11-07): fuselage, wing, power pod, landing gear, wing hold-down skewers done; motor mounted (not wired); 4 servos installed and linked. Camera opening, avionics mounting, wing fit, surface setup and CG still to do; see `progress/airframe.md` |

### Pi ↔ FC wiring (UART4 = SERIAL4, TELEM connector)

The FC's TELEM connector is the white GH1.25 6-pin on the FC's edge opposite the USB-extender board. Counting from the end nearest the GPS/camera edge (away from the servo pins), its pins are `GND, RX2, TX2, RX4, TX4, 4V5` (ArduPilot `CoreWingF405WMiniV2/README.md`). The same RX4/TX4 signals are on the front pads `5V T4 R4 G`.

| FC | Pi 3 / Zero 2 W header | Note |
|---|---|---|
| TELEM pin 1 GND (or pad G) | physical pin 6 (GND) | required, or nothing works |
| TELEM pin 4 RX4 (or pad R4) | physical pin 8 (GPIO14 TXD) | |
| TELEM pin 5 TX4 (or pad T4) | physical pin 10 (GPIO15 RXD) | |
| TELEM pin 6 4V5 (or pad 5V), plus pins 2 and 3 | **nothing**; tape the ends | the Pi and FC each get their own power |

Check before powering: with the wires off, pin 10 must follow the Pi's pull-up/pull-down. With the wires on and the FC running, pin 10 must idle HIGH and show activity.

## Flight gates (also `config/flight_gates.toml`; the governor enforces these)

| Gate | Status |
|---|---|
| F0 ground checks | not started |
| F1 FBWA maiden with recording | not started |
| F2 AUTO survey via uplink | not started |
| F3 practice approaches + go-around | not started |
| F4 Cloudbreak end-to-end | not started |
