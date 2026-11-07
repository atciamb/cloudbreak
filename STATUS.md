# Cloudbreak — Master Status

**Last merged:** 2026-11-07 ≈18:00 (≈H7.0; H0 = Sat 11:00) · **Code freeze H20 (Sun 07:00)** · **Devpost due H22 (Sun 09:00)** · **Coding stops H24 (Sun 11:00)**

**Merged so far:**
- **P1** updates 17:11, 17:31, 17:37
- **P2** update 17:21
- **Software / HITL** from the repo:
  - HITL bench test (17:34, `9cd547e`)
  - geofence + FC configuration through the Pi (17:53, `cb18601`)
  - read: `docs/CHECKLIST.md`, `docs/SESSION_LOG.md`, `README.md`, `config/`, `scripts/`
- **P1's sources:** Mission Planner logs (13:50, 14:25) and `docs/hardware/fc/inav_8.0.1_backup_20261107.txt`
- **Still missing:** written updates from **P3** (Pi & camera) and **P4** (FC & radio). Their rows below come from the repo and P1's notes.

> **How this file works.** Each person posts an update in [`docs/updates/`](docs/updates/README.md) using the template. Each merge rewrites this file: gate board, blockers and plan. A gate is ticked only with evidence. Evidence lives in `docs/CHECKLIST.md` (tests) and `config/flight_gates.toml` (flight gates). This file is the cross-team picture. *(Supersedes `docs/hardware/TEAM_STATUS.md` and `progress/`, merged here at H7.0.)*

---

## 0 · Headline
- **Software is essentially done.**
  - S1–S3 pass, and the S4 end-to-end SITL flow passes. S4 accuracy needs real Tutor data.
  - The **signed command path through the Pi passed HITL on the real FC** (17:33, 10/10).
  - **Geofence set on the FC** (Schuyler polygon, breach → RTL); the param audit is now 17/17.
  - FC parameters can now be changed **through the Pi**, without USB.
- **Hardware is the critical path, about 2.5 h behind.**
  - The FC has to go to P1 **cold** for power-board soldering (G1 → G2), and every hardware gate after that waits on it.
- **The airframe is mechanically built** (P2).
  - Camera opening, bay layout and wing fit can start now.
  - Surface setup waits for G2 + output mapping (≈21:00). Install and CG are ≈23:00.
- **Top hazards:**
  - Output mapping still at defaults (ESC must not go on S1 yet).
  - Possible 4V5 back-feed from the wiring incident (FC settings verified intact; the hardware question is still open).
  - **The fence now blocks arming outside the Schuyler polygon**, which matters for any bench test that needs arming (§2).
- **Decision needed now:** flight scope (§5).
  - A real flight before judging is effectively ruled out by daylight.
  - With the fence, **Schuyler can't host a governed autoland at all**.

## 1 · Gate board
### Hardware commissioning (prop off throughout)
| Gate | What it proves | Status | Evidence / note |
|---|---|---|---|
| **G0** | Board identified | ✅ Pass | INAV backup: `INAV/COREWINGF405WMINIV2 8.0.1`. Banner: `ArduPlane V4.7.2 (fb773567)`, `CoreWingF405WMiniV2` |
| — | Firmware + Cloudbreak FC parameters | ✅ Applied | CHECKLIST: param backup 1137/1137, `fc_setup_usb.py` applied (sysid 42, signing, MAV stream rates, FS settings, WP_RADIUS 20). Re-verified through the Pi at 17:46: only intended changes. **Servo outputs not touched** (see §2) |
| — | Geofence on the FC | ✅ Set (bench) | 17:48: Schuyler 21-vertex polygon uploaded and read back identical. FENCE_TYPE 5, ACTION 1 (RTL), ALT_MAX 100 m, RET_ALT 50, OPTIONS 0, ENABLE 1; RTL_ALTITUDE → 50. Not yet checked outdoors with a GPS fix |
| — | Airframe build (P2) | ◐ Built, untested | Fuselage, wing, power pod, gear, skewers done. Motor mounted (not wired). 4 servos installed + linked. Not a gate; feeds G3 (surfaces) and F0 (CG) |
| **G1** | Harness checked cold | ⬜ **Blocked** | P1 is waiting for the FC hand-over (it's on the Pi/HITL bench) |
| **G2** | First power, numbers logged | ⬜ | After G1 |
| **G3** | Radio + surfaces correct | ⬜ | Outputs still at ArduPlane defaults (S1 = aileron, S3 = throttle). Accelerometer calibration needed. No receiver yet. Surface work = P2 step A4 |
| **G3b** | GPS + compass + log | ⬜ | "Compass 1 not healthy" (nothing connected yet) |
| **G4** | Pi ↔ FC MAVLink **on UBEC** | ◐ **Partial** | MAVLink passes over TELEM/UART4 at 230400 (FC→Pi 17:14; signed HITL 17:33). That was a Pi 3 on its own supply with the FC on USB. **Not yet done:** Pi on the UBEC, voltage under load, the Zero 2 W |
| **G5** | Integrated bench run | ⬜ | — |

### Software / demo
| Gate | Status | Evidence (`docs/CHECKLIST.md`) |
|---|---|---|
| **S1** SITL + mission writer | ✅ Pass | ArduPlane 4.7.2 SITL. Signing, read-back hash, hold, GCS failsafe→RTL, commit, DO_GO_AROUND, throttle abort, link loss after commit |
| **S2** Map + ranked candidates | ✅ Pass (synthetic/oracle) | Evidence grid from synthetic frames. Real-image segmenter works on ortho crops but fails on synthetic renders, so oracle perception is used in SITL (labelled) |
| **S3** Approval + governor | ✅ Pass | OTP approval; refusals for wrong code, unknown obstacle height and battery < 30 %; agent isolation tests |
| **S4** End-to-end SITL landing | ◐ Flow passes; **accuracy not acceptable** | Session demo2: landed 71 m past the aim point (strip ends at +36 m). Cause: the SITL airframe's ~6 % glide vs a 12 % approach |
| HITL signed command path via Pi | ✅ Pass | `hitl_20261107T173318.json`: 10/10. Unsigned, wrong-sysid, PARAM_SET and DO_SET_MODE dropped at the Pi; wrong-key and direct-unsigned ignored by the FC |
| Param audit for real uploads | ✅ Pass | 17:49: 17/17 audited values match, including the fence and RTL altitude (`hitl_20261107T174904.json`). HITL re-run 10/10 |
| FC configuration through the Pi | ✅ Pass | `scripts/fc_params_pi.py` backup/audit/apply/fence. PARAM_SET only forwarded in an SSH-opened maintenance window while disarmed. Link/identity/arming params stay USB-only |
| **D1** Demo recorded + Devpost | ⬜ | — |

### Flight ladder (`config/flight_gates.toml`)
F0 ground checks · F1 maiden · F2 AUTO survey · F3 practice approaches · F4 end-to-end: **all not started.** F0 can't start before G5.

## 2 · Safety flags (read before touching hardware)
1. 🔴 **No ESC on S1 until the output mapping is fixed and P1 has checked it on screen.** Required values:
   - `SERVO1_FUNCTION=70` (ESC)
   - `SERVO2_FUNCTION=0`
   - `SERVO3_FUNCTION=4` (left aileron)
   - `SERVO4_FUNCTION=4` (right aileron)
   - `SERVO5_FUNCTION=19` (elevator)
   - `SERVO6_FUNCTION=21` (rudder)

   At the moment S1 sends an aileron-centre signal, which could mean about half throttle.
2. 🟠 **Wiring incident on the Pi↔FC link** (CHECKLIST). The FC's **settings** were verified intact through the Pi (17:46). But the FC still reports `POWER_STATUS Vcc = 0`, so a **4V5 back-feed hasn't been ruled out** in hardware; P1 checks the 4V5 and FC 5 V readings at G2. **TELEM pin 6 (4V5) and pins 2–3 stay taped.** The FC holder owes P1 a short write-up.
3. 🟠 **Every session with the Pi wired to the FC goes through the power marshal (P1)**, the same as USB and battery sessions.
4. The prop stays in its bag. No soldering unless the hardware is COLD. Electronics booting ≠ flight readiness.
5. During USB-only FC sessions, the GPS and the Pi link are unplugged or both boards are powered (the 4V5 pins are live on USB).
6. 🟠 **Fence + arming.** With FENCE_ENABLE=1, the FC refuses to arm outside the Schuyler polygon, which includes the bench. Any prop-off bench test that needs the FC armed (e.g. motor direction through the FC) needs a plan from P4 + software first: what to change, who approves, and a re-audit to 17/17 afterwards. Before flying anywhere, upload that site's fence (`fc_params_pi.py fence --site <key>`).

## 3 · Workstream status
### P1 · Power & integration (power marshal) · Iain — *update 17:37*
- **Done:** G0; M1.B power prep (UBEC set to 5 V, ESC photographed with red contact not lifted, XT60 lead on 14 AWG, leads tinned).
- **Now:** waiting for the FC hand-over. Meanwhile, off-board prep: capacitor, lead lengths, GPS harness by function, UBEC → Pi lead, LiPo cell log.
- **Lane:** about 2.5 h behind (G2 was due at H4). This lane is the project's critical path.

### P2 · Airframe · Andrew — *update 17:21*
- **Done:** Tutor fuselage, wing, power pod, landing gear, wing hold-down skewers. Motor mounted (not wired). 4 servos glued in, horns on and linked.
- **Untested:** motor direction; servo neutral, direction and throw; wing fit; CG; all-up weight.
- **Now (no power needed):**
  - A1 camera opening (nadir, recessed, foam soft-mount)
  - A2 bay layout dry-fit
  - A3 wing fit and aileron lead reach to S3/S4
- **Later:**
  - A4 surface setup at G3 (≈21:00)
  - Install, then A5 CG at 57–63 mm and weight (≈23:00–00:00)
- **Needs:** camera cable length (P3); bay layout agreement (P1 + P4); output mapping (P4).
- Full detail: [`docs/updates/P2_2026-11-07_1721.md`](docs/updates/P2_2026-11-07_1721.md).

### P3 · Pi & camera — *no written update (repo shows Pi 3 progress)*
- **From the repo:**
  - Pi 3 bench: Trixie 64-bit, camera, frame server and MAVLink bridge all run.
  - The bridge points at the real FC (`/dev/serial0` @ 230400).
  - HITL passed through it.
- **Needed:**
  - When the **Zero 2 W** swap happens (SD card + 22-pin ribbon + field-hotspot Wi-Fi).
  - The Pi power plan for G4. The repo asks for 5.1–5.2 V at the Pi, but our UBEC is fixed at 5.0 V, so measure for sag.
  - The camera cable length for P2.

### P4 · FC & radio — *no written update*
- **From P1 / repo:** ArduPlane 4.7.2 flashed with P1. Output mapping still at defaults. Accelerometer calibration not done. No receiver bound yet.
- **Needed:**
  - Output mapping + accelerometer calibration (≤20 min USB session)
  - Pocket EdgeTX/ELRS versions
  - Receiver bind plan
  - When the FC can be handed to P1

### Software (repo; maps to the P3/P4 software rows)
- S1–S3 pass and the S4 flow passes in SITL. Priors are built. The local LLM agent runs. Autoland BO done on the SITL airframe.
- `scripts/hitl_bench.py` passed on the real FC (17:33; re-run 10/10 at 17:49). `config/targets.toml` points the real target at the Pi's bench address (169.254.77.2); at the field this becomes the Zero's hotspot address.
- **17:53, geofence + FC config through the Pi:**
  - Schuyler fence polygon uploaded and enabled on the FC.
  - The planner and governor require every path point to be 20 m inside the fence, and the governor refuses real missions at a site with no fence.
  - Desired FC params now live in `config/fc_params.toml`. 65 tests on that branch.
- **Site finding:** with the fence, **no governed landing pattern fits at Schuyler**. The approach plus go-around is ~350–400 m, more than the park allows. Schuyler is for manual flying, surveys and practice inside the fence. Anderson Field (no fence drawn yet) and SITL are the autoland options.
- **Open:**
  - `SensorTimestamp` clock-domain check still proposed
  - S4 accuracy needs a real Tutor sysid log (flight only)
  - Thresholds need re-calibration on labelled real frames

## 4 · Blockers & dependencies
| Blocker | Blocks | Owner | Unblocks when |
|---|---|---|---|
| **FC is on the Pi/HITL bench** | M1.C soldering, G1, G2, and everything after | Software team → P1 | FC handed over COLD (USB + Pi pigtail off) |
| Output mapping at defaults | ESC on S1, servo centring, G3 / P2 A4 | P4 | Values confirmed on screen by P1 |
| Wiring-incident details | Clearing the 4V5 back-feed concern | FC holder | Write-up in CHECKLIST + P1 inspection at G2 (4V5 / FC 5 V readings) |
| Pad photo + ESC photo review | Capacitor location; ESC red contact | P1 → AI | Photos sent |
| No receiver bound | G3, all pre-arm | P4 | XR1 wired after G2 |
| Bay layout not agreed | P2 A2 (gluing), install at ≈23:00 | P2 + P1 + P4 | Layout agreed on the dry-fit |
| Camera cable length unknown | P2 A1 final cut | P3 | P3 confirms which Zero ribbon we have |
| Fence blocks arming off-site | Any bench test that needs the FC armed | P4 + software | Agreed bench procedure, re-audit afterwards (§2 flag 6) |
| No autoland-capable site with a fence | Real governed autoland (not bench, not SITL) | Team | Anderson Field fence + permission, if flight stays in scope |

## 5 · Decisions
| Decision | Status |
|---|---|
| Pi ↔ FC baud | ✅ **230400** (`SERIAL4_BAUD=230`, Pi `air.toml` matches). Replaces 115200 in the original plan |
| Pi link connector | ✅ TELEM GH1.25: pin 1 GND → Pi pin 6, pin 4 RX4 → Pi pin 8, pin 5 TX4 → Pi pin 10. Pins 2, 3 and 6 taped |
| Output mapping | ⬜ S1 ESC (70), S3/S4 ailerons (4), S5 elevator (19), S6 rudder (21). Set by P4, checked by P1 |
| Capacitor location | ⬜ middle ESC pads (after photo + continuity check) or short leads to B+/B− |
| XR1 power pin | ⬜ receiver header 4V5, if ≥4.5 V under battery at G2 |
| Pi Zero 2 W swap timing | ⬜ recommend **before G4-on-UBEC**, so the power test uses the real load |
| Camera mount | ⬜ P2 proposes nadir, recessed, foam soft-mount. Confirm with P3 |
| Fence parameters | ✅ Schuyler polygon (21 vertices, 12.3 ha, ≥19 m from buildings), FENCE_TYPE 5, ACTION 1 (RTL), ALT_MAX 100 m, RET_ALT 50, OPTIONS 0; RTL_ALTITUDE 50. Planner/governor margin 20 m inside |
| **Scope: real flight / autoland** | ⚠️ **Needs explicit team agreement.** The repo session log puts real autoland in scope behind F0–F4. The original handoff made it optional. Timing: F0 can't start before G5 (planned H15, 02:00), sunrise is ≈06:35, code freeze is 07:00 and Devpost is due 09:00. Add a learning pilot, an open site/LAANC question and no Remote ID hardware, and **F1 before judging is effectively out**. Also, with the fence, Schuyler can't host a governed autoland; Anderson Field has no fence drawn. **Suggested (not yet agreed):** demo = S4 SITL end-to-end + live bench hardware at the last gate passed (G4/G5); real flight after the event |
| Rest rota | ⬜ re-plan; at least 2 people awake |

## 6 · Remaining plan — hardware critical path
P1 re-baselined this at H6.6. P2 rows were added at H7.0.

| Window (H) | Clock | Step | Who |
|---|---|---|---|
| now → ≈7.0 | →18:00 | Finish the current FC session (fence + Pi config done at 17:53). Optional ≤20 min session: output mapping (USB, or `fc_params_pi.py`, then confirmed on screen by P1) + accelerometer calibration. Then **hand over COLD** | Software team / P4 |
| 7.0 – 10.0 | 18:00–21:00 | **Airframe prep, parallel, no power:** A1 camera opening, A2 bay layout dry-fit (agree with P1/P4 before any glue), A3 wing fit + aileron lead reach. Record the motor label. Mark the CG range on the wing | P2 |
| 7.0 – 8.5 | 18:00–19:30 | **M1.C** power-board soldering → **G1** | P1 |
| 8.5 – 9.0 | 19:30–20:00 | **G2** first power (stack + ESC + UBEC). Check the 4V5 / FC 5 V readings for incident damage | P1 |
| 9.0 – 10.0 | 20:00–21:00 | XR1 wiring + bind + radio calibration. ESC → S1 after mapping is checked. ESC calibration with prop off. Motor direction check | P4 + P1 |
| 10.0 – 11.0 | 21:00–22:00 | Servos: FC centres, pushrods reset to neutral, throws, directions in MANUAL and FBWA, failsafe → **G3** (P2 A4) | P2 + P4 + P1 |
| 11.0 – 11.5 | 22:00–22:30 | GPS harness on, indoor detection, FC log card | P1 + P4 |
| 11.5 – 12.0 | 22:30–23:00 | Pi (Zero 2 W if swapped) on the UBEC + TELEM link → **G4** (link already proven, so this is mostly the power test) | P3 + P1 |
| 12.0 – 13.0 | 23:00–00:00 | **Install in the airframe** per the A2 layout; camera soft-mounted; TELEM pins taped. At the end: **CG + all-up weight** (P2 A5) | P2 + P1 |
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
- **FC holder:** what was the wiring incident? When can the FC be handed over? (COM5 matters less now that parameters can be set through the Pi.)
- **P4:** output mapping + accelerometer calibration done? Pocket EdgeTX/ELRS versions? Receiver bind plan?
- **P3:** which Zero camera ribbon do we have (length)? Zero 2 W swap time? Pi power plan for G4?
- **P2:** motor label; A1–A3 done? CG marks checked against the kit manual?
- **P4 + software:** how will prop-off bench tests that need arming work with the fence enabled (§2 flag 6)?
- **Team:** flight scope (§5). If flight stays in scope: Anderson Field fence + permission.

## 8 · Where things live
| What | Where |
|---|---|
| This combined picture | `STATUS.md` |
| Personal updates + template + who's who | [`docs/updates/`](docs/updates/README.md) |
| Evidence ledger (tests, bench, HITL) | `docs/CHECKLIST.md` |
| Flight gates F0–F4 (governor reads these) | `config/flight_gates.toml` |
| Flight roles, abort drills, go/no-go | `docs/FLIGHT_CARDS.md` |
| Software session log + design decisions | `docs/SESSION_LOG.md`, `docs/sitl_notes.md` |
| FC backups | `docs/hardware/fc/` |

## 9 · Sources
- `docs/updates/P1_2026-11-07_1711_M1B.md`, `P1_2026-11-07_1731.md`, `P1_2026-11-07_1737.md`, `P2_2026-11-07_1721.md`
- Repo `atciamb/cloudbreak` `main`, including `9cd547e` (HITL), `cb18601` (geofence + FC config through the Pi) and `docs/CHECKLIST.md`
- `docs/hardware/fc/inav_8.0.1_backup_20261107.txt`; P1's Mission Planner tlogs (13:50, 14:25)
