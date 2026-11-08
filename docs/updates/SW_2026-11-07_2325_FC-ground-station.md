# Cloudbreak — Personal Update

**Who / role:** Software · key holder (the software laptop, which has `C:\cb-data\keys\mavlink_real.key`)
**Time sent:** 2026-11-07 23:25 (≈H12.4)
**Rows on the team chart this covers:** M2 step 1 (output map) · the Mission Planner blocker (P1 21:27) · FC checks toward G3/G3b
**Power state:** FC on the software laptop's USB (COM5), **USB power only**, no battery (BATT reads 0.8 V), no ESC. Prop in its bag (per P1 22:51).

## 1 · Done since my last update
| Item | Evidence |
|---|---|
| **Mission Planner blocker (P1 21:27) fixed: signing proxy** `scripts/gcs_proxy.py`. Mission Planner or QGC connects to it on UDP 14550; repo scripts use `tcp:127.0.0.1:5770`. It checks the FC's signatures and strips them on the way down, and signs everything on the way up. It never forwards SETUP_SIGNING, so signing stays on and nothing on the FC changes. One click: `scripts\mission_planner_signed.bat` | `docs/CHECKLIST.md` row "Ground station on the signed FC". Real FC: 153 msgs/3 s unsigned to a key-less client; 6 signed PARAM_SETs confirmed; it rode through an FC reboot. 10 tests |
| Mission Planner 1.3.83 installed on the software laptop | MSI from firmware.ardupilot.org. **MP's own connection through the proxy not yet exercised** (needs a person at the laptop) |
| Why MP saw nothing: confirmed | Raw capture: 209/209 frames signed, **all verify with the team key**. The FC's signing clock reads 21:21 UTC (key install) because there's no GPS time yet. That is harmless; it moves forward when a signed message or GPS time arrives |
| **Output map set** (STATUS §2 #1) through the proxy, 23:09, FC disarmed: SERVO1_FUNCTION 70, 2 = 0, 3 = 4, 4 = 4, 5 = 19, 6 = 21. Also in `config/fc_params.toml [outputs]` and the governor's pre-upload audit | Read-back: `C:\cb-data\fc\bench_outputs_20261107T231307.json`; backup before: `params_backup_20261107T230859.parm` |
| ⚠️ **S1 after the change** (see §8): fixed SERVO3_TRIM 1100 → 1500 and rebooted. Now **S1 1100 µs** disarmed, S2 no pulses, S3–S6 1500 µs | same read-back (`bench_outputs_20261107T232400.json`) |
| microSD card in the FC: **present and healthy** (P1's 22:51 open question) | logging healthy; no `No SD card` / `Logging failed` pre-arm; 0 logs yet (it logs only when armed) |
| GPS detected (no fix indoors); compass **QMC5883L at I2C 0x0D** detected | GPS_RAW_INT fix_type 1; COMPASS_DEV_ID 855297; live magnetometer values |
| `scripts/fc_bench.py`: status / outputs / rc / logs / accel / level / compass / radio, with or without Mission Planner. Each run writes `C:\cb-data\fc\bench_*.json` | compass-cal flow checked on the bench (start → progress → cancel, nothing saved) |

## 2 · Gates I'm claiming
None. The output map is the first M2 step, not a gate. P1 still has to check it.

## 3 · In progress right now
- Leaving the proxy running on the software laptop with the FC on COM5.

## 4 · Blocked / waiting on
| What I need | From whom | Since |
|---|---|---|
| On-screen check of the output map (`fc_bench.py outputs` or MP Setup → Servo Output), then the ESC (red contact lifted) on S1 | P1 | 23:13 |
| XR1 bound to the Pocket: RC_CHANNELS shows **0 channels** (`Waiting for RC`). SERIAL6 = RCIN is set correctly. Then radio cal (`fc_bench.py radio` or MP) | P4 | — |
| Someone to turn the bare FC through 6 positions for the **accel calibration** (`fc_bench.py accel` detects each position itself; or MP) | P4 / anyone at the software laptop | — |
| Compass calibration + GPS fix: outdoors, installed in the airframe (`fc_bench.py compass --accept`) | P1 + P4 at G3b | — |
| FC → Zero UART still 0 bytes on `/dev/serial0` (TELEM to header pins 6/8/10) | P1 + P3 at G4 | 21:30 |

## 5 · Power events I need from the marshal
- USB stays as it is for bind, radio calibration and accel calibration (the FC is on the software laptop's USB now).
- BATT for G3 servo checks (the servos are powered from the BEC/UBEC, not USB).

## 6 · Measurements / readings
- Disarmed outputs after the reboot: S1 1100, S2 off, S3 1500, S4 1500, S5 1500, S6 1500 µs.
- Battery monitor on USB: 0.81 V (no pack).
- The GPS powers up with only USB connected, which suggests its VCC is on the FC 4V5 (option A in P1's 22:51 list). **P1 to confirm.**

## 7 · Next 2 hours
Accel calibration as soon as someone can rotate the FC → radio calibration once bound → hand the FC to P1 for the ESC on S1 → G3 servo directions (MP via the proxy, FBWA then MANUAL) and the TX-off failsafe check.

## 8 · Problems, surprises, questions
- ⚠️ **After changing SERVOn_FUNCTION, reboot the FC before plugging anything in.** S1 kept putting out **1500 µs** after it became the throttle output, roughly half throttle on a calibrated ESC. It dropped to the 1100 µs minimum only after a reboot. S3 also kept its old throttle trim (1100), which would have parked that aileron at full deflection. `fc_bench.py outputs` now flags both.
- Mission Planner must connect via **UDP 14550**, not the FC's COM port (the proxy holds it). Don't use MP's "MAVLink Signing" page: the proxy refuses SETUP_SIGNING anyway.
- The proxy can also run through the Pi (`--fc tcp:<zero>:14560`), but the Pi's filter still drops PARAM_SET (outside a maintenance window) and mode commands. For calibrations, use USB on the laptop that has the key.
