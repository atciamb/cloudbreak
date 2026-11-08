# F2 run card: AUTO survey at Schuyler (real aircraft)

Read aloud. One person per role (`docs/FLIGHT_CARDS.md`). The governor will **refuse** F2 until F0 **and** F1 are recorded in
`config/flight_gates.toml` with evidence (log file, video, initials). Nobody edits that file except to record a gate that passed.

## 0 · Before you leave (bench, done 2026-11-08 unless marked)
- [x] Output map, servo directions MANUAL + FBWA, radio + accel calibration, flight modes, low-battery failsafe (`docs/CHECKLIST.md`)
- [x] Schuyler fence on the FC; param audit clean (22/22); signed path through the Pi 3 (HITL ALL PASS 05:18)
- [ ] Pi 3 power: `vcgencmd get_throttled` = `0x0` from boot, camera running (capacitor / shorter leads)
- [ ] After install: `fc_bench.py status` (compass + RC present), FC booted **still** (gyros), **Calibrate Level** (`fc_bench.py level`)
- [ ] CG 57–63 mm with the Pi 3 aboard; throws; prop type (motor turns CCW seen from the front)

## 1 · Field network (laptop + Pi on the same Wi-Fi)
The SD card auto-joins **Derek's iPhone XR** hotspot. Turn it on before powering the plane.
1. Power the plane (power owner). The Pi joins the hotspot in about 40 s.
2. Read the Pi's address from the phone's hotspot client list, then on the laptop:
   ```powershell
   $env:CLOUDBREAK_PI_HOST = "<pi address>"
   $env:CLOUDBREAK_SITE = "schuyler"
   ```
3. A new address isn't in the trusted host list yet, so confirm it is our card before trusting it:
   ```powershell
   ssh-keyscan -t ed25519 <pi address> > $env:TEMP\pi.key; ssh-keygen -lf $env:TEMP\pi.key
   ```
   It must print `SHA256:wX0D2NRnz0rV78+As+LiQbFgY7b9TmbPFSKbiufJgLY`. If so, append it to `C:\cb-data\keys\known_hosts_pi`.
4. Check the Pi: `http://<pi address>:8080/status` shows `capture.frames` rising and `bridge.streams_ok: true`.

## 2 · F0 ground checks (record in `config/flight_gates.toml` only when all pass)
- [ ] `.venv\Scripts\python scripts\fc_params_pi.py audit --site schuyler` → 0 differences, fence 21 vertices
- [ ] `.venv\Scripts\python scripts\hitl_bench.py` → ALL PASS over the field Wi-Fi (RTT < 800 ms)
- [ ] GPS 3D fix, ≥ 8 satellites, HDOP ≤ 2; compass calibrated (`fc_bench.py compass --accept`, installed, outdoors)
- [ ] Control directions MANUAL **and** FBWA (tilt check), TX-off failsafe with outputs powered, prop off
- [ ] Range check (ELRS Lua: TX power to minimum, walk away, surfaces still respond; restore power)
- [ ] Mode switch FBWA / AUTO / RTL; consent switch CH7 reads > 1700 when ON; abort drill rehearsed
- [ ] Battery charged; CG; go/no-go list in `docs/FLIGHT_CARDS.md`

## 3 · F1 maiden (FBWA, manual), then record it
Hand launch FBWA, climb to 40–60 m, trim, RTL/LOITER in and out, **≥ 3 LOITER circles at 40 m**, land FBWA.
Download the DataFlash log + Pi session. Set `turn_radius_m` in `config/aircraft_tutor.toml` from the log (survey turns use it).
Record F0 and F1 in `config/flight_gates.toml` (evidence + date + initials).

## 4 · F2 AUTO survey
Laptop, two windows:
```powershell
.venv\Scripts\python -m cloudbreak.ground.governor.governor --target real     # shows the one-time code; page :8710
.venv\Scripts\python -m cloudbreak.ground.core.api --target real --source pi --perception aerial --pi-url http://$env:CLOUDBREAK_PI_HOST`:8080
```
1. Pilot launches in **FBWA** and climbs to about 40 m. The governor's checks include *armed and airborne* for landings only; for the
   survey it needs: gates F0+F1, GPS/EKF healthy, battery ≥ 30 %, path inside the fence, param audit, link fresh, **consent switch ON**.
2. Ground operator: core page `http://127.0.0.1:8700` → **survey →** on a nomination (40 m).
3. Governor page `http://127.0.0.1:8710`: enter the one-time code and `FLY xxxx` → **Execute**. It uploads, reads back, and compares
   the hash. A refusal lists the failing checks: fix them or abandon.
4. Pilot flips the mode switch to **AUTO** at survey height (the ground never selects AUTO on the real aircraft).
5. Pilot takes over in **FBWA** at any doubt. **RTL** brings it home at 50 m. Battery failsafe RTLs at 10.5 V.
6. Land manually in FBWA. Pull the Pi session (`/tlog`, frames) for the map.

Abort words: anyone may call **ABORT** → pilot to FBWA. Hard end 11:00.
