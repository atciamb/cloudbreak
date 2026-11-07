# ArduPlane SITL — build, ports, verified behaviours

ArduPilot `Plane-4.7.2` (same release as the CoreWingF405WMiniV2 flight controller), built in WSL Ubuntu 24.04.

## Build / run

```powershell
wsl -d Ubuntu -u root -- bash /mnt/c/dev/cloudbreak/sim/sitl/build.sh deps    # apt (root, no sudo prompt)
wsl -d Ubuntu          -- bash /mnt/c/dev/cloudbreak/sim/sitl/build.sh build   # clone + waf (~2 min on 20 cores)
.\sim\sitl\run_sitl.ps1 -Speedup 4                                             # run (Ctrl-C or stop_sitl.sh to stop)
wsl -d Ubuntu -- bash /mnt/c/dev/cloudbreak/sim/sitl/stop_sitl.sh
```

- The binary is run directly (`arduplane -S --model plane ... </dev/null`). Without `-S` and stdin redirected,
  it exits with code 1 under a non-interactive `wsl` launch.
- Defaults: `Tools/autotest/models/plane.parm`, then `sim/sitl/tutor_like.parm`. In 4.7.2, `default_params/plane.parm` doesn't exist.
- `--wipe` on each start (`-KeepEeprom` to keep params). The signing key lives in EEPROM, so a wipe clears it.

## Port map (instance I adds 10·I)

| Port | SITL serial | Use |
|---|---|---|
| 5760 | SERIAL0 | **Keeper only.** SITL blocks at boot until this connects, and **exits when it disconnects**. `run_sitl.sh` holds it with a bash `/dev/tcp` reader. It plays the role of the real FC's USB port. Never connect anything else here (even `Test-NetConnection` kills SITL). |
| 5762 | SERIAL1 | Governor, read-write, signed. Plays the role of the real FC SERIAL4 via the Pi. Streams from `MAV2_*`. |
| 5763 | SERIAL2 | Core, read-only, unsigned. Streams from `MAV3_*`. |
| 5765 | SERIAL5 | QGC / `fc_relay` (`SERIAL5_PROTOCOL 2`) |

WSL2 NAT localhost forwarding makes these reachable from Windows at `127.0.0.1`. No `.wslconfig` or netsh changes needed.

## Parameter names verified in 4.7.2 (stock values in `C:\cb-data\sitl_params_stock.txt`)

`ARSPD_TYPE`/`ARSPD_USE` (stock SITL 2/1, i.e. it simulates an airspeed sensor, so Tutor-like sets 0/0),
`AIRSPEED_CRUISE` (stock 22), `TRIM_THROTTLE`, `LAND_PITCH_DEG`, `LAND_FLARE_ALT/SEC`, `LAND_ABORT_THR`,
`TECS_LAND_THR` (stock −1 = off), `TECS_LAND_SINK`, `FS_GCS_ENABL`, `FS_LONG_ACTN`, `FS_LONG_TIMEOUT` (stock 5),
`MAV_GCS_SYSID` (stock 255), `MAVn_EXTRA1/EXTRA2/EXTRA3/POSITION/EXT_STAT/RC_CHAN/RAW_SENS/OPTIONS`
(`SRn_` is gone), `RTL_AUTOLAND`, `AUTOLAND_*`, `SIM_WIND_SPD/DIR/TURB/TC/T*`, `SIM_SPEEDUP`, `SIM_BARO_DRIFT`,
`SIM_BARO_RND`, `SIM_GPS1_*` (GPS sim params are per-instance in 4.7), `SERIAL5_PROTOCOL` (stock −1).

## Findings that changed the design

1. **`DO_LAND_START` blocks arming** ("Arm: DO_LAND_START set and RTL_AUTOLAND disabled"). The landing sequence
   no longer uses it. The abort resumes at `NAV_CONTINUE_AND_CHANGE_ALT`, and `RTL_AUTOLAND` stays 0, so a link-loss RTL
   goes home instead of into a landing.
2. **Mission read-back normalisation.** `*_INT` frames come back as float frames (6→3, 5→0); `DO_JUMP` comes back in frame 0;
   `NAV_LOITER_TO_ALT` param1 is dropped; `NAV_LAND` param4 is rewritten. `common/mav.py::canonical_items`
   normalises exactly these, so `mission_hash(sent) == mission_hash(read_back)`.
3. **Duplicate items get NACKed with `MAV_MISSION_INVALID_SEQUENCE`**, and the transfer continues. The uploader treats this as non-fatal.
4. **On Windows `time.monotonic()` ticks at about 16 ms.** Protocol waits use `time.perf_counter()`, otherwise
   one `MISSION_REQUEST` matches twice and floods duplicates.
5. RC override and GCS-failsafe heartbeats are only honoured from `MAV_GCS_SYSID` (245 = governor). The SITL
   "sim pilot" (arming, throttle-up) uses sysid 245 / compid 191 and sends **no** heartbeats, so it can't mask
   governor link loss.

## Verification run (`sim/sitl/verify_sitl.py`, 4× speed, wind 3 m/s from 200°, turbulence 0.5)

Result file `C:\cb-data\sitl_verify\verify_20261107T125818.json`: **all PASS**.

| Check | Result |
|---|---|
| E1 MAVLink2 signing | Before the key, an unsigned `REQUEST_MESSAGE` was ACKed. After `SETUP_SIGNING`, an unsigned command was **ignored** and a signed one ACKed. The unsigned reader still received ATTITUDE (age 0.01 s). |
| E2 upload → read-back hash | Match (`d280646689c691fa`, 8 items) |
| E3 `NAV_LOITER_UNLIM` hold | Held 30 sim-s at 40 m in AUTO |
| E4 governor heartbeat loss in hold | **RTL after 17 sim-s** (`FS_GCS_ENABL=1`, `FS_LONG_ACTN=1`) |
| E5 commit | `MAV_CMD_DO_SET_MISSION_CURRENT` breaks the hold and the mission advances |
| E6 `MAV_CMD_DO_GO_AROUND` on NAV_LAND at 11 m | ACK 0, climbs to the go-around item, `DO_JUMP` back to the hold |
| E7 pilot throttle > 90 % (RC override ch3 = 1950) at 11 m | Abort, then back to the hold (`LAND_ABORT_THR=1`) |
| E8 heartbeats cut after commit | **Lands in AUTO.** Touchdown 3.7 m short / 1.1 m left of the aim point, 9.7 m/s groundspeed, 0.64 m/s sink, 29 m rollout. 13.6 s wall from commit to stop at 4×. |

Caveat: the SITL `plane` model is a generic ~22 m/s airframe, not a Tutor. Absolute touchdown dispersion and rollout
do **not** transfer. The Tutor-like file only matches the *sensor suite* (no airspeed sensor, no rangefinder). `sysid.py` anchors
SITL to real flight logs once they exist.
