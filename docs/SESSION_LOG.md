# Cloudbreak session log

## 2026-11-07 (Sat), software build session (Claude + team)

**Decisions (from the team)**
- Real autonomous landing and a ground→Pi→FC uplink are in scope, behind the governor, MAVLink2 signing and flight gates F0–F4.
- The LLM is local only (Ollama). The safety pilot is still learning. No rangefinder: the software has to learn to autoland with what the plane has.
- Link-loss policy: hold before the commit point; after commit, the FC finishes the landing.
- Code lives in `C:\dev\cloudbreak`; data, keys and sessions in `C:\cb-data`. The G: Drive folder is not used.

**Environment found**
- Laptop: i7-13700H, 32 GB RAM, RTX 2000 Ada 8 GB.
- WSL Ubuntu 24.04, plus uv-managed CPython 3.11 (the Microsoft Store Python 3.11 won't launch).
- Pi 3: link is up, but it has no IPv4 (NetworkManager on a bare cable) and the Windows "Public" firewall profile drops its traffic. **Waiting on Windows ICS** (Wi-Fi → Ethernet 3).

**Verified facts used in the design (sources: ArduPilot docs and source, Raspberry Pi docs)**
- FC target `CoreWingF405WMiniV2`, ArduPlane 4.7.2. SERIAL4 = UART4 (Pi link): set `SERIAL4_BAUD=115`. In 4.7, `SRn_` became `MAVn_`.
- This build has no Lua, terrain database or MAVLink camera backend, so geotagging happens on the Pi.
- Signing: non-USB ports ignore unsigned commands once a key is set, and telemetry keeps flowing. Verified in SITL.
- 4.7.2 refuses to arm with `DO_LAND_START` unless `RTL_AUTOLAND` is set, so the landing sequence doesn't use it (found in SITL).
- Read-back normalisation of mission items found in SITL; the canonical hash handles it.
- Picamera2 `SensorTimestamp` = first-pixel readout, CLOCK_BOOTTIME.

**Priors (all free, no auth)**
- NYS 2024 orthophoto, 0.3 m RGB + CIR.
- USGS 3DEP 1 m DEM.
- USGS LiDAR from AWS EPT: NY_Hudson_1_D22 (2022) preferred, NY_FEMAR2_Central_4_2018 to fill.
- OSM, FAA DOF, Open-Meteo.
- Grid: EPSG:32618 at 0.5 m.

**Findings**
- '86 Field is not autolandable with this airframe and these margins: the best approach misses LiDAR clearance by 4.9 m.
- Anderson Field works: landing heading about 100°, 12 % glide from 20 m, 15 % missed-approach climb, +2 m margin.
- SITL verification all PASS (`docs/sitl_notes.md`): signing, read-back hash, hold, GCS failsafe in hold → RTL, commit, DO_GO_AROUND, throttle abort, link loss after commit still lands.
- In the integrated SITL run, the governor correctly refused (a) a survey over a LiDAR coverage hole (unknown obstacle height) and (b) execution with the battery below 30 %.

**Bugs found and fixed during integration**
- Windows `time.monotonic()` resolution (16 ms) caused a duplicate-mission-item flood; switched to `perf_counter`.
- Small LiDAR no-return pockets were treated as unknown height; they are now filled with the max of the surrounding heights.
- The planner held the GIL and starved the frame loop. It now re-plans every 8 s and evaluates strips in a window.
- A single stray "person" pixel blocked cells. Sightings now use the per-cell aggregated probability (unit test added).
- The LiDAR-noise roughness threshold was 0.08 m on max HAG; it is now p90 HAG at 0.30 m.

- Survey nominations were re-ranked on every plan, so "nomination 2" moved between areas. They are now prior-only and cached.
- The "every cell ≥ 0.75" rule was a multiple-comparisons trap. Replaced with every cell ≥ 0.60 (no weak spots), plus a strip mean ≥ 0.75, with hazards still judged per cell. Added a SITL ground-truth threshold-calibration endpoint (`/api/ro/calibrate`, split-conformal quantile on hazard cells).
- SITL TCP serial ports are single-client. After a client is killed, WSL's localhost relay can keep the slot held. The governor now switches surveys to AUTO in SITL only; on the real aircraft the pilot does this.
- System ID on a SITL DataFlash log: the generic SITL plane glides ~16:1 (max ~6 % slope), so it floats on 12 % approaches. The Tutor's real log is needed to set the approach.

- Survey lines were never flown: the stock `WP_RADIUS` (50 m) made the plane cut 250 m lines short, and a 10 m lawnmower is impossible with a 25–100 m turn radius. Now `WP_RADIUS 20` (SITL and FC setup) plus interleaved line order (consecutive lines about 47 m apart).
- Double-counted margins: hazards were buffered by wingspan/2 + 2σ_nav on top of a strip width that already included those. The hazard buffer is now 1 m (map geolocation error only).
- Last look redesigned: a nadir camera can't see the point a loiter circles (the plane banks 45–63° and looks outward). The mission now has a straight look leg over the strip along its axis, triggered from the hold, which returns to the hold. Commit requires at least 3 fresh views.
- **SITL end-to-end autoland completed** (session demo2, audit chain valid). Accuracy is not acceptable yet: it stopped 71 m past the aim point (strip ends at +36 m). Expected, given the SITL airframe's ~6 % max glide vs the 12 % approach. This is the reason for real sysid, BO re-tuning and gate F3.
- Local LLM agent ran (qwen3:4b, about 2 s per proposal). It sometimes disagrees with the planner, e.g. it called feasible C01a "no_safe_site" citing a low p_lb_min. Advisory only; the human decides.

**Pi bring-up (15:00–15:25)**
- Pi 3 B, Raspberry Pi OS Trixie 64-bit, user `pidrone`, hostname `raspberrypi`. It was already on campus Wi-Fi with internet (ICMP blocked; HTTP works). ICS was not needed in the end.
- Key installed via `scripts/install_pi_key.ps1`. eth0 now has a static `169.254.77.2/16` (NetworkManager "Wired connection 1"), on the same link-local subnet as the laptop.
- Camera, picamera2, OpenCV and simplejpeg were preinstalled. `setup_pi.sh` removed the serial login console and installed the services. Air config is in **bench mode**: `fc_url = tcp:127.0.0.1:5770` (SITL via `ssh -R 5770:127.0.0.1:5765`). **Set it back to `/dev/serial0` once the FC is wired to UART4.**
- Under-voltage with the touch display attached went away after it was unplugged.
- Switched to console boot (`raspi-config nonint do_boot_behaviour B1` → `multi-user.target`) and disabled `wayvnc`/`wayvnc-control`; re-enable with `sudo systemctl enable --now wayvnc` plus boot option B4 if a desktop is wanted. Used RAM is about 340 MB on the Pi 3, mostly the capture service's camera buffers (~160 MB, capped at 220 MB). Still running and untouched, and could be disabled if the Zero runs short: pipewire/wireplumber (audio), cups, ModemManager, rpi-connectd (~100 MB together).
- The pre-existing `~/mav.parm`, `~/mav.tlog` and venvs were left untouched.

**Not done / not verified**
- Nothing has run on the real Pi or FC yet.
- No flight.
- The CABiNet real-image segmenter isn't wired in yet (oracle perception only, labelled).
- Ollama model install still in progress.
- Autoland BO is running (SITL generic airframe; must be re-anchored with real logs via sysid).

**Next for the hardware team**
1. Enable ICS.
2. Install the SSH key (`ssh-copy-id`-equivalent below).
3. `scripts/deploy_pi.sh user@192.168.137.x --setup`, then reboot.
4. Camera test.
5. FC on USB → `scripts/fc_setup_usb.py --port COMx` (dry run), then `--apply` after review.
6. HITL bench.
7. F0.
