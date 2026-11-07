# Cloudbreak

Cloudbreak is an RC plane (Flite Test Tutor, ArduPlane 4.7.2 on a CoreWing F405 Wing Mini V2). It finds a landing strip from its own downward camera plus free public geodata, explains the choice, and lands only after a human approves and a deterministic governor agrees. Built for HackRPI 2026.

**Status (7 Nov 2026)**

- **Done and tested:** SITL, governor, planner, priors and core all work end to end. Unit tests pass (43). SITL behaviours are verified (see `docs/sitl_notes.md`).
- **Written, not yet run on hardware:** the air-side code (Pi capture, MAVLink bridge, frame server).
- **Not done:** no real flight has happened. See `docs/CHECKLIST.md` for what is and isn't verified.

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

Every cell needs at least 3 good views and a 5 % lower credible bound P(safe) ≥ 0.75 to count as safe. Unknown is never safe.

The **planner** searches strips at every heading and scores them with explained terms. It checks the approach and missed-approach path against the LiDAR surface model.

The **governor** is the only process that writes to the aircraft:
- It rebuilds the mission itself and hashes it.
- A human approves it with a one-time code shown only in the governor console.
- It checks the target fingerprint, telemetry, EKF, battery, clearance, flight gates and parameters.
- It uploads the mission signed, reads it back and verifies the hash.
- It flies hold, then last look, then commit, then land. It aborts by itself if the site is invalidated.

The **agent** only proposes; it cannot approve or command anything.

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

## Pi (air side)

```bash
scripts/deploy_pi.sh <user>@<pi-ip> --setup     # once; then sudo reboot (UART change)
scripts/deploy_pi.sh <user>@<pi-ip>             # later updates
```

The same SD card later moves to the Pi Zero 2 W. Swap the camera ribbon for the 22-pin Zero cable, and set the Zero's Wi-Fi to the field hotspot.

## Layout

- `cloudbreak/common/`: schemas, geodesy, MAVLink link and mission hash, mission builder, clearance, audit log, clock model.
- `cloudbreak/air/`: Pi services.
- `cloudbreak/ground/core/`: priors, geometry, mapping, planner, environment, API, UI.
- `cloudbreak/ground/governor/`: approval, checks, execution, approval page.
- `cloudbreak/ground/agent/`: local LLM agent and template fallback.
- `cloudbreak/ground/autoland/`: SITL Bayesian optimisation and touchdown dispersion.
- `sim/`: SITL scripts, synthetic camera, sim pilot.
- `config/`: site, targets, aircraft, flight gates.
- `scripts/`: Pi deploy and FC USB setup.

Data, keys, weights and sessions live in `C:\cb-data`, never in git.
