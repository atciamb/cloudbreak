# Cloudbreak — Master Status

**Last merged:** 2026-11-07 ≈18:30 (≈H7.5; H0 = Sat 11:00) · **Devpost due H22 (Sun 09:00)** · **Code freeze = coding stops H24 (Sun 11:00)**. Flying and testing continue after the freeze.

**Merged so far:**
- **P1** updates 17:11, 17:31, 17:37
- **P2** updates 17:21, 18:30
- **Software / HITL** from the repo:
  - HITL bench test (17:34, `9cd547e`)
  - geofence + FC configuration through the Pi (17:53, `cb18601`)
  - read: `docs/CHECKLIST.md`, `docs/SESSION_LOG.md`, `README.md`, `config/`, `scripts/`
- **P1's sources:** Mission Planner logs (13:50, 14:25) and `docs/hardware/fc/inav_8.0.1_backup_20261107.txt`
- **Still missing:** written updates from **P3** (Pi & camera) and **P4** (FC & radio). Their rows below come from the repo and P1's notes.

> **How this file works.** Each person posts an update in [`docs/updates/`](docs/updates/README.md) using the template. Each merge rewrites this file: gate board, blockers and plan. A gate is ticked only with evidence. Evidence lives in `docs/CHECKLIST.md` (tests) and `config/flight_gates.toml` (flight gates). This file is the cross-team picture. *(Supersedes `docs/hardware/TEAM_STATUS.md` and `progress/`, merged here at H7.0.)* Wiring reference: [`docs/hardware/WIRING.md`](docs/hardware/WIRING.md).

---

## 0 · Headline
- 🎯 **End goal for Sunday:** demo the full governed autoland in SITL **plus real flight data from the Tutor**.
  - **F1** FBWA maiden at first light (≈06:35), with the Pi recording.
  - Then the **F2** AUTO survey through the signed uplink, if time allows.
  - Coding stops at 11:00, but flying and testing don't, so flights can continue into the demo window.
  - Real autoland (F3/F4) is *not* this weekend (§5).
- ⏱️ **To fly at ≈06:35, F0 has to pass by ≈04:00.** That means G1 → G5 tonight with almost no slack.
  - The hardware lane (P1) is the critical path.
  - **The first blocker is handing the FC to P1, cold, now.**
- ✅ **Software is essentially done.** S1–S3 pass; the S4 SITL flow passes; HITL passes on the real FC (10/10); the fence is set and the audit is 17/17. FC parameters can be changed through the Pi.
- ✈️ **The airframe is built** (P2). Camera opening, bay layout and wing fit happen now; surfaces at G3 (≈21:30); install + CG ≈23:30.
- 🔌 **Wiring:** full diagram + connection tables in [`docs/hardware/WIRING.md`](docs/hardware/WIRING.md).
- ⚠️ **Top hazards:**
  - Output map still at defaults (no ESC on S1 yet).
  - Possible 4V5 back-feed.
  - The fence blocks arming at the bench, which affects ESC calibration and the motor direction check (§2 #6).
  - Pi pin 6 is double-booked (§2 #7).
- 🟡 **Before F1** (go/no-go at the field, not a bench item):
  - site permission
  - **Remote ID**: a broadcast module or a FRIA site; none was ordered
  - LAANC if Schuyler (KALB Class C)
  - the right site fence loaded
  - wind
  - four roles staffed

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
**Targets:** F0 02:30–04:00 Sun · F1 ≈06:35 · F2 09:00–11:00 if F1 is clean · F3/F4 after the event.

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
6. 🟠 **Fence + arming.** With FENCE_ENABLE=1, the FC refuses to arm outside the Schuyler polygon, and the bench is outside it. Arming also needs every other pre-arm item cleared (RC, accel, compass, GPS home), so indoors isn't possible anyway. **ArduPilot's plane ESC calibration arms the FC**, and so does a motor direction check through the FC. P4 + software pick a method and P1 approves it:
   - **(a)** ESC calibration + motor direction with a **servo tester** instead of the FC (no arming), if we have one;
   - **(b)** check P1's ESC label photo: if the ESC doesn't need calibrating, only motor direction remains;
   - **(c)** in the outdoor G3b slot, a supervised prop-off session with FENCE_ENABLE=0 set through `fc_params_pi.py`. Then **re-enable and re-audit to 17/17 before anything else**.

   Before flying anywhere, upload that site's fence (`fc_params_pi.py fence --site <key>`).
7. 🟠 **Pi pin 6 is double-booked.** The proven TELEM GND is on Pi pin 6. P1's UBEC→Pi lead was drafted as pin 2 (+5 V) / pin 6 (GND). **Move the UBEC GND to pin 14** (or 9 / 20). The GPIO 5 V pins have no reverse-polarity protection, so meter polarity before plugging in.
8. 🟡 **F1 go/no-go** (legal + safety, decided at the field; not a bench item). Any "no" means no flight:
   - Site permission (Aeromodeling Club).
   - **Remote ID**: the Tutor is well over 0.55 lb, so it needs a broadcast module, or must fly at a FAA-Recognized Identification Area (FRIA). None was ordered.
   - Schuyler is inside KALB Class C, so it needs **LAANC** before every flight.
   - That site's fence loaded, with the audit at 17/17.
   - Wind ≤ 5 m/s.
   - All four flight-card roles staffed, and the pilot comfortable.

## 3 · Workstream status
### Tonight at a glance
| Who | Now → ≈21:30 | Later tonight | Sunday |
|---|---|---|---|
| **P1** Iain (power) | Take the FC cold → M1.C soldering → G1 → **G2 by ≈20:30** | Radio/ESC with P4 → G3 → GPS → G4 → install → G3b → G5 → F0 | Power owner at the field (proposed) |
| **P2** Andrew (airframe) | A1 camera opening · A2 bay dry-fit (agree with P1/P4) · A3 wing fit · motor label · CG marks | G3 servos (≈21:30) · install + **CG/weight** (≈23:30) · F0 CG + structure | Devpost lead: draft overnight, **submit by 09:00**. Flight role TBD |
| **P3** (Pi & camera) | Zero 2 W swap (SD card, 22-pin ribbon, hotspot Wi-Fi) · re-pin the UBEC lead (§2 #7) · tell P2 the ribbon length | **G4** (≈23:00) · Pi recording checked in G5 | Pi recording during F1/F2 |
| **P4** (FC & radio) | Output map + accel cal before the hand-over · Pocket switches (FBWA/AUTO/RTL, RC7 consent) · ELRS bind prep · ESC-calibration method (§2 #6) | Bind + radio cal + ESC (≈20:30) → G3 → GPS → G3b | Flight role TBD |
| **Software** | **Hand the FC to P1 now** · field config (Pi hotspot address in `config/targets.toml`, fence for the flight site) · Devpost skeleton | G5 support · fence audit for F0 | sysid on the F1 log · ground operator for F2 (proposed) |

### P1 · Power & integration (power marshal) · Iain — *update 17:37*
- **Done:** G0; M1.B power prep (UBEC set to 5 V, ESC photographed with red contact not lifted, XT60 lead on 14 AWG, leads tinned).
- **Now:** waiting for the FC hand-over. Meanwhile, off-board prep: capacitor, lead lengths, GPS harness by function, UBEC → Pi lead, LiPo cell log.
- **Lane:** about 2.5 h behind (G2 was due at H4). This lane is the project's critical path.

### P2 · Airframe · Andrew — *updates 17:21, 18:30*
- **Done:** Tutor fuselage, wing, power pod, landing gear, wing hold-down skewers. Motor mounted (not wired). 4 servos glued in, horns on and linked.
- **Untested:** motor direction; servo neutral, direction and throw; wing fit; CG; all-up weight.
- **Now (no power needed):**
  - A1 camera opening (nadir, recessed, foam soft-mount)
  - A2 bay layout dry-fit
  - A3 wing fit and aileron lead reach to S3/S4
- **Later:**
  - A4 surface setup at G3 (≈21:30)
  - Install, then A5 CG at 57–63 mm and weight (≈23:30–00:30)
  - F0: CG + structural check (A7); Devpost lead by 09:00
- **Needs:** camera cable length (P3); bay layout agreement (P1 + P4); output mapping (P4).
- Full detail: [`docs/updates/P2_2026-11-07_1721.md`](docs/updates/P2_2026-11-07_1721.md) and [`P2_2026-11-07_1830.md`](docs/updates/P2_2026-11-07_1830.md).

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
| Remote ID / site / LAANC | F1 (not the bench) | Team + Aeromodeling Club | FRIA site or Remote ID module; LAANC if Schuyler; site permission (§2 #8) |
| Pi pin 6 double-booked | G4 | P1 + P3 | UBEC GND moved to pin 14 (§2 #7) |
| No autoland-capable site with a fence | Real governed autoland (F3/F4, after the event) | Team | Anderson Field fence + permission |

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
| **Scope: real flight** | ✅ **Plan (Andrew, 18:05): fly Sunday.** Coding stops at 11:00 (H24); the earlier internal 07:00 freeze is dropped, and flying/testing continue after 11:00. Target: F0 overnight, then the F1 FBWA maiden at ≈06:35, then the F2 AUTO survey if time allows. Every flight is still subject to the go/no-go in §2 #8. **F3/F4 (real autoland) are not this weekend**: they need sysid + BO re-tuning from real logs, practice approaches, and a site where the pattern fits (Schuyler doesn't; Anderson Field has no fence) |
| Flight site for F1 | ⬜ The Schuyler fence is on the FC (needs LAANC + Remote ID or a FRIA). A club field needs its own fence uploaded first |
| Flight roles | ⬜ PIC · ground operator · safety observer · power owner, one each (`docs/FLIGHT_CARDS.md`). Proposed: P1 power owner, software ground operator |
| ESC calibration method under the fence | ⬜ servo tester / skip if not needed / supervised outdoor fence-off (§2 #6) |
| UBEC → Pi pins | ⬜ +5 V pin 2, GND **pin 14** (§2 #7) |
| Rest rota | ⬜ 04:00–06:00, at least 2 awake (attended LiPo charging) |

## 6 · Remaining plan — tonight → first flight → demo
P1's hardware path, re-baselined at H7.5 for a Sunday-morning flight. Each window starts as soon as the one before it passes; if the FC hand-over slips, shift everything after it by the same amount.

| Window (H) | Clock | Step | Who |
|---|---|---|---|
| 7.5 | 18:30 | **FC handed over COLD** (USB + Pi pigtail off). If there's time first: output map (`fc_params_pi.py` or USB; P1 checks on screen) + accel cal | Software / P4 |
| 7.5 – 9.0 | 18:30–20:00 | **M1.C** power-board soldering → **G1** cold checks | P1 |
| 7.5 – 10.5 | 18:30–21:30 | *Parallel, no power:* airframe A1–A3, motor label, CG marks | P2 |
| 7.5 – 10.5 | 18:30–21:30 | *Parallel:* Zero 2 W swap; UBEC lead re-pinned; ribbon length to P2 | P3 |
| 7.5 – 9.0 | 18:30–20:00 | *Parallel:* Pocket model + switches; ELRS bind prep; ESC-calibration method agreed | P4 (+ software) |
| 7.5 – 15.5 | 18:30–02:30 | *Parallel:* field config (hotspot address, site fence), Devpost skeleton | Software |
| 9.0 – 9.5 | 20:00–20:30 | **G2** first power; log the readings (`WIRING.md` §9) | P1 |
| 9.5 – 10.5 | 20:30–21:30 | XR1 wiring + bind + radio cal → ESC on S1 (after the map check) → ESC calibration + motor direction, prop off (§2 #6) | P4 + P1 |
| 10.5 – 11.5 | 21:30–22:30 | **G3** servos: centre, pushrods to neutral, throws, directions in MANUAL **and FBWA**, TX-off failsafe | P2 + P4 + P1 |
| 11.5 – 12.0 | 22:30–23:00 | GPS harness on, indoor detection, log card | P1 + P4 |
| 12.0 – 12.5 | 23:00–23:30 | **G4** Pi Zero on the UBEC + TELEM; ≥5.1 V at the Pi with the camera running | P3 + P1 |
| 12.5 – 13.5 | 23:30–00:30 | **Install in the airframe** per the A2 layout → **CG + all-up weight** | P2 + P1 |
| 13.5 – 14.0 | 00:30–01:00 | Outdoor GPS fix + compass calibration → **G3b** | P1 + P4 |
| 14.0 – 15.5 | 01:00–02:30 | **G5** integrated bench run (real bridge + governor read-only) | P1 + software |
| 15.5 – 17.0 | 02:30–04:00 | **F0 ground checks**: CG, MANUAL + FBWA directions, TX-off failsafe (prop off), flight-site fence loaded + audit 17/17, range check, switches, abort drill → evidence in `config/flight_gates.toml` | All |
| 17.0 – 19.0 | 04:00–06:00 | Rest rota (≥2 awake): attended pack charging, Devpost draft, field kit packed | Rota |
| 19.0 – 19.5 | 06:00–06:30 | At the field: **go/no-go** (§2 #8) | All |
| 19.6 – 20.5 | ≈06:35–07:30 | **F1** FBWA maiden: hand launch, Pi recording. Download the DataFlash log + Pi session | All |
| 20.5 – 22.0 | 07:30–09:00 | `sysid.py` on the F1 log · **Devpost submitted by 09:00** · F2 prep if F1 was clean | Software · P2 (Devpost) |
| 22.0 – 24.0 | 09:00–11:00 | **F2** AUTO survey at 40 m through the signed uplink (stretch; needs F0 + F1 recorded) → real imagery into core. Any code or param changes done by 11:00 | All |
| **24.0** | 11:00 | **Coding stops.** Flying and testing can continue | All |
| 24.0+ | 11:00→ | Demo: SITL end-to-end governed autoland + real F1/F2 data (live flight if permitted) | All |

### Decision points
- **20:30 (H9.5):** G2 not passed → bench-demo fallback (FC USB telemetry + Pi camera on its own supply). A flight becomes unlikely.
- **22:30 (H11.5):** G3 not passed → no flight Sunday; demo = SITL + bench.
- **02:30 (H15.5):** G5 not passed → the team decides between F0 + F1 with FC DataFlash logging only (Pi recording optional), or stopping hardware for demo polish.
- **04:00 (H17):** F0 not passed → no flight.
- **06:30:** go/no-go at the field. Any "no" is final for that slot, with no pressure to fly.
- **Never cut:** human approval · governor · signed, SITL-separated command path · logging · labels on synthetic data · pilot takeover · pre-arm checks.

## 7 · Questions for the next round of updates
- **FC holder:** hand the FC over now. What was the wiring incident?
- **P1:** UBEC GND moved to Pi pin 14? Capacitor location?
- **P4:** output map + accel cal done? Pocket EdgeTX/ELRS versions? Which ESC-calibration method (§2 #6)?
- **P3:** which Zero ribbon (length)? Zero 2 W swap done?
- **P2:** motor label; A1–A3 done? CG marks checked against the kit manual?
- **Team / club:** flight site, Remote ID (module or FRIA), LAANC, flight roles, who's PIC.

## 8 · Where things live
| What | Where |
|---|---|
| This combined picture | `STATUS.md` |
| Personal updates + template + who's who | [`docs/updates/`](docs/updates/README.md) |
| Evidence ledger (tests, bench, HITL) | `docs/CHECKLIST.md` |
| Flight gates F0–F4 (governor reads these) | `config/flight_gates.toml` |
| Flight roles, abort drills, go/no-go | `docs/FLIGHT_CARDS.md` |
| Software session log + design decisions | `docs/SESSION_LOG.md`, `docs/sitl_notes.md` |
| Wiring diagram + connection tables + remaining-step guides | [`docs/hardware/WIRING.md`](docs/hardware/WIRING.md) |
| FC backups | `docs/hardware/fc/` |

## 9 · Sources
- `docs/updates/P1_2026-11-07_1711_M1B.md`, `P1_2026-11-07_1731.md`, `P1_2026-11-07_1737.md`, `P2_2026-11-07_1721.md`, `P2_2026-11-07_1830.md`
- ArduPilot CoreWingF405WMiniV2 board README (Plane-4.7.2); ArduPilot plane ESC calibration (arming required); FAA Remote ID / FRIA rules
- Repo `atciamb/cloudbreak` `main`, including `9cd547e` (HITL), `cb18601` (geofence + FC config through the Pi) and `docs/CHECKLIST.md`
- `docs/hardware/fc/inav_8.0.1_backup_20261107.txt`; P1's Mission Planner tlogs (13:50, 14:25)
