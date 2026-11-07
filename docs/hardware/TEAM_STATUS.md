# Cloudbreak — Combined Team Status

**Last merged:** 2026-11-07 17:37 (≈H6.6; H0 = Sat 11:00) · **Devpost due H22 (Sun 09:00)** · **Coding stops H24 (Sun 11:00)**

**Merged so far:**
- P1 written updates (17:11, 17:31, 17:37)
- Team repo `atciamb/cloudbreak`: `main` @ b36bcaa (17:30), `full-stack` @ 9cd547e (17:34). Read: `docs/CHECKLIST.md`, `docs/SESSION_LOG.md`, `README.md`, `scripts/`, `config/`
- This laptop's Mission Planner logs (13:50, 14:25) and `docs/hardware/fc/inav_8.0.1_backup_20261107.txt`
- **Still missing:** written updates from P2, P3 and P4. Software and Pi status below comes from the repo.

> **How this file works.** Each person sends an update using `updates/TEMPLATE.md`. Updates are merged here, and the gate board, blockers and remaining plan are rewritten. A gate is ticked only with evidence. The repo's `docs/CHECKLIST.md` stays the evidence ledger for software and HITL; this file is the cross-team picture.

---

## 1 · Gate board
### Hardware commissioning (prop off throughout)
| Gate | What it proves | Status | Evidence / note |
|---|---|---|---|
| **G0** | Board identified | ✅ Pass | `inav_backup.txt`: `INAV/COREWINGF405WMINIV2 8.0.1`. Banner: `ArduPlane V4.7.2 (fb773567)`, `CoreWingF405WMiniV2` |
| — | Firmware + Cloudbreak FC parameters | ✅ Applied | Repo CHECKLIST: param backup 1137/1137, `fc_setup_usb.py` applied (sysid 42, signing, MAV stream rates, FS settings, WP_RADIUS 20). Dry re-run shows 0 changes |
| **G1** | Harness checked cold | ⬜ **Blocked** | P1 is waiting for the FC to be handed over (it's on the Pi/HITL bench) |
| **G2** | First power, numbers logged | ⬜ | After G1 |
| **G3** | Radio + surfaces correct | ⬜ | **Outputs still at ArduPlane defaults** (S1 = aileron, S3 = throttle); `fc_setup_usb.py` doesn't touch servos. Accelerometer calibration needed. No receiver yet |
| **G3b** | GPS + compass + log | ⬜ | "Compass 1 not healthy" (nothing connected yet) |
| **G4** | Pi ↔ FC MAVLink **on UBEC** | ◐ **Partial** | MAVLink passes over TELEM/UART4 at 230400 (FC→Pi 17:14; signed HITL 17:33). That was a Pi 3 on its own supply with the FC on USB. **Not yet done:** Pi on the UBEC, voltage under load, the Zero 2 W |
| **G5** | Integrated bench run | ⬜ | — |

### Software / demo
| Gate | Status | Evidence (repo `docs/CHECKLIST.md`) |
|---|---|---|
| **S1** SITL + mission writer | ✅ Pass | ArduPlane 4.7.2 SITL. Signing, read-back hash, hold, GCS failsafe→RTL, commit, DO_GO_AROUND, throttle abort, link loss after commit |
| **S2** Map + ranked candidates | ✅ Pass (synthetic/oracle) | Evidence grid from synthetic frames. Real-image segmenter works on ortho crops but fails on synthetic renders, so oracle perception is used in SITL (labelled) |
| **S3** Approval + governor | ✅ Pass | OTP approval; refusals for wrong code, unknown obstacle height and battery < 30 %; agent isolation tests |
| **S4** End-to-end SITL landing | ◐ Flow passes; **accuracy not acceptable** | Session demo2: landed 71 m past the aim point (strip ends at +36 m). Cause: the SITL airframe's ~6 % glide vs a 12 % approach |
| HITL signed command path via Pi | ✅ Pass | `hitl_20261107T173318.json`. Unsigned, wrong-key and disallowed commands were dropped or ignored |
| **D1** Demo recorded + Devpost | ⬜ | — |

### Flight ladder (repo `config/flight_gates.toml`)
F0 ground checks · F1 maiden · F2 AUTO survey · F3 practice approaches · F4 end-to-end: **all not started.** F0 can't start before G5.

## 2 · Safety flags (read before touching hardware)
1. 🔴 **No ESC on S1 until the output mapping is fixed and P1 has checked it on screen.** Required values:
   - `SERVO1_FUNCTION=70`
   - `SERVO2_FUNCTION=0`
   - `SERVO3_FUNCTION=4`
   - `SERVO4_FUNCTION=4`
   - `SERVO5_FUNCTION=19`
   - `SERVO6_FUNCTION=21`

   At the moment S1 sends an aileron-centre signal, which could mean about half throttle.
2. 🟠 **Wiring incident on the Pi↔FC link (repo CHECKLIST).** The FC reports `POWER_STATUS Vcc = 0`, so a **4V5 back-feed hasn't been ruled out**. COM5 also showed Windows error 31. **TELEM pin 6 (4V5) and pins 2–3 stay taped.** P1 needs a short write-up of what happened.
3. 🟠 **From now on, every session with the Pi wired to the FC goes through the power marshal**, the same as USB and battery sessions.
4. The prop stays in its bag. No soldering unless the hardware is COLD. Electronics booting ≠ flight readiness.
5. During USB-only FC sessions, the GPS and the Pi link are unplugged or both boards are powered (the 4V5 pins are live on USB).

## 3 · Workstream status
### P1 · Power & integration (power marshal) — *update 17:37*
- **Done:** G0; M1.B power prep (UBEC set to 5 V, ESC photographed with red contact not lifted, XT60 lead made, leads tinned).
- **Now:** waiting for the FC hand-over. Meanwhile, off-board prep: capacitor, lead lengths, GPS harness by function, UBEC → Pi lead, LiPo cell log.
- **Lane:** about 2.5 h behind (G2 was due at H4). **The hardware lane is now the critical path**, because the software gates are largely done.

### Software team (repo; maps to the P2/P3/P4 software rows)
- S1–S3 pass and S4 flow passes in SITL. Priors are built. Local LLM agent runs. Autoland BO done on the SITL airframe.
- Air side on a **Pi 3**: OS Trixie 64-bit, camera, frame server and MAVLink bridge all run. Bridge now points at the real FC (`/dev/serial0` @ 230400).
- **Open (from the repo):**
  - `FENCE_ENABLE=0`, so the governor refuses real uploads (team decision needed)
  - `SensorTimestamp` clock-domain check still proposed
  - S4 accuracy needs a real Tutor sysid log (flight only)
  - thresholds need re-calibration on labelled real frames

### P2 · Airframe — *no update*
Needed: build state (wing, fuselage, servos glued, horns off?), bay layout, kit CG range, motor label. Servo centring needs G2 + output mapping, so expect it about H10.

### P3 · Pi & camera — *no written update (repo shows Pi 3 progress)*
Needed: when the **Zero 2 W** swap happens (SD card + 22-pin ribbon + Wi-Fi), and the Pi-side power plan for G4 (UBEC to pins 2/6; the repo asks for 5.1–5.2 V at the Pi, but our UBEC is fixed at 5.0 V, so measure for sag).

### P4 · FC & radio — *no written update*
Needed: output mapping + accelerometer calibration (≤20 min USB session); Pocket EdgeTX/ELRS versions; receiver bind plan; when the FC can be handed to P1.

## 4 · Blockers & dependencies
| Blocker | Blocks | Owner | Unblocks when |
|---|---|---|---|
| **FC is on the Pi/HITL bench** | M1.C soldering, G1, G2, and everything after | Software team → P1 | FC handed over COLD (USB + Pi pigtail off) |
| Output mapping at defaults | ESC on S1, servo centring, G3 | P4 | Values confirmed on screen by P1 |
| Wiring-incident details | Clearing the 4V5 back-feed concern | Software team | Write-up in CHECKLIST + P1 inspection at G2 (4V5 / FC 5 V readings) |
| Pad photo + ESC photo review | Capacitor location; ESC red contact | P1 → AI | Photos sent |
| No receiver bound | G3, all pre-arm | P4 | XR1 wired after G2 |
| Fence undecided | Real-aircraft governor uploads (not bench) | Team | Fence decision |

## 5 · Decisions
| Decision | Status |
|---|---|
| Pi ↔ FC baud | ✅ **230400** (`SERIAL4_BAUD=230`, Pi `air.toml` matches). Replaces 115200 in the original plan |
| Pi link connector | ✅ TELEM GH1.25: pin 1 GND → Pi pin 6, pin 4 RX4 → Pi pin 8, pin 5 TX4 → Pi pin 10. Pins 2, 3 and 6 taped |
| Capacitor location | ⬜ middle ESC pads (after photo + continuity check) or short leads to B+/B− |
| XR1 power pin | ⬜ receiver header 4V5, if ≥4.5 V under battery at G2 |
| Pi Zero 2 W swap timing | ⬜ recommend **before G4-on-UBEC**, so the power test uses the real load |
| Fence parameters | ⬜ team |
| Scope: real autoland | ⚠️ The repo session log has it in scope behind F0–F4. The handoff made it optional. Needs explicit team agreement, plus pilot readiness, site, LAANC and Remote ID (the repo notes Schuyler is in KALB Class C; no Remote ID was ordered). Not a bench blocker |
| Rest rota | ⬜ re-plan; at least 2 people awake |

## 6 · Remaining plan — hardware critical path (re-baselined at H6.6)
| Window (H) | Clock | Step | Who |
|---|---|---|---|
| now → ≈7.0 | 17:40–18:00 | Finish the current FC session. Optional ≤20 min USB: output mapping + accelerometer calibration. Then **hand over COLD** | Software team / P4 |
| 7.0 – 8.5 | 18:00–19:30 | **M1.C** power-board soldering → **G1** | P1 |
| 8.5 – 9.0 | 19:30–20:00 | **G2** first power (stack + ESC + UBEC). Check the 4V5 / FC 5 V readings for incident damage | P1 |
| 9.0 – 10.0 | 20:00–21:00 | XR1 wiring + bind + radio calibration. ESC → S1 after mapping is checked. ESC calibration with prop off | P4 + P1 |
| 10.0 – 11.0 | 21:00–22:00 | Servos: centre, directions in MANUAL and FBWA, failsafe → **G3** | P2 + P4 + P1 |
| 11.0 – 11.5 | 22:00–22:30 | GPS harness on, indoor detection, FC log card | P1 + P4 |
| 11.5 – 12.0 | 22:30–23:00 | Pi (Zero 2 W if swapped) on the UBEC + TELEM link → **G4** (link already proven, so this is mostly the power test) | P3 + P1 |
| 12.0 – 13.0 | 23:00–00:00 | Install in the airframe | P2 + P1 |
| 13.0 – 13.5 | 00:00–00:30 | Outdoor fix + compass calibration → **G3b** | P1 + P4 |
| 13.5 – 15.0 | 00:30–02:00 | **G5** integrated run with the real bridge + governor in read-only/telemetry mode | P1 + software team |
| 15.0 – 17.5 | 02:00–04:30 | P1 rest; hardware LOCKOUT | — |
| 17.5 – 20.0 | 04:30–07:00 | Logger/replay with real bench data; record the bench session; demo pack charge | P1 |
| **20.0** | 07:00 | **Code freeze** | All |
| 20.0 – 22.0 | 07:00–09:00 | Backup video; **Devpost by 09:00** | P2 lead |
| 22.0 – 24.0 | 09:00–11:00 | Rehearse; live demo power script | All |

### Decision points (build guide cut list)
- **H10 (21:00):** if G2 hasn't passed → the live bench demo uses FC USB telemetry + the Pi camera on its own supply (the link has already been proven over TELEM).
- **H12 (23:00):** if G3 hasn't passed → the demo shows the airframe static. Radio authority is shown on a bench FC only.
- **H15 (02:00):** if G5 hasn't passed → freeze the hardware at the last gate that passed and record it. Everyone moves to demo polish.
- **Never cut:** human approval · governor · signed, SITL-separated command path · logging · labels on synthetic data · pilot takeover · pre-arm checks.

## 7 · Questions for the next round of updates
- **FC holder:** what was the wiring incident? Has COM5 error 31 cleared? When can the FC be handed over?
- **P4:** output mapping + accelerometer calibration done? Pocket versions?
- **P2:** airframe state, CG range, motor label?
- **P3:** Zero 2 W swap plan; Pi power plan for G4?

## 8 · Sources
- `updates/P1_2026-11-07_1711_M1B.md`, `updates/P1_2026-11-07_1731.md`, `updates/P1_2026-11-07_1737.md`
- Repo `atciamb/cloudbreak` (local clone `Documents/Cloudbreak/repo`, branch `full-stack`)
- `docs/hardware/fc/inav_8.0.1_backup_20261107.txt`; this laptop's Mission Planner tlogs
