# Cloudbreak — Master Status

**Last merged:** 2026-11-08 01:00 (≈H14.0; H0 = Sat 11:00) · **Hard end H24 (Sun 11:00): flying and coding both stop.** ⚠️ **Devpost:** HackRPI's published schedule says projects must be on Devpost **by 09:00 Sunday**. This conflicts with "Devpost isn't a deadline" below; see §5.

**Changed in this merge (software 01:00):** battery on the bench, motor on the ESC, prop off ([`SW_2026-11-08_0100`](docs/updates/SW_2026-11-08_0100_motor.md)):
- ✅ **Motor spins through the FC** (bench procedure §2 #6 (d), P1-approved): counter-clockwise from the front at about 19 % throttle. The FC was restored and re-audited after every run (37 values + fence polygon).
- ⚠️ The ESC signal lead was on the **SBUS pad**, not S1. Moved to S1 (red still lifted).
- ✅ **Low-battery failsafe set** (it was off): RTL after 10 s below 10.5 V.
- ⚠️ First arm attempt refused (`Logging not started`: slow SD card); the retry worked. Expect the same at the field.

**Previous merge (software 00:26):** bench tests with the FC and the Pocket at the software laptop ([`SW_2026-11-08_0026`](docs/updates/SW_2026-11-08_0026_bench-tests.md)):
- ✅ Mission Planner connected through the proxy (its log: 842 FC messages accepted).
- ✅ Accel calibration (bare FC); ✅ XR1 bound (16 channels); ✅ radio calibration; ✅ flight modes FBWA / AUTO / RTL (switch-low used to be RTL).
- ✅ Pocket switches: CH8 mode switch, CH7 consent (latching, 2000 when ON). Before tonight nothing was mapped to CH5–CH8.
- ✅ TX-off failsafe, FC side (bench): CIRCLE at once, RTL after 19 s, cleared when the Pocket came back.
- ⚠️ The bare-board level step left AHRS trim at roll −6.7°: **Calibrate Level after install** is now required, not optional.

*Previous merge (software 23:25, plus P1 22:51 and P2 22:30):*
- ✅ **Mission Planner blocker fixed without touching signing.** `scripts/gcs_proxy.py` on the key-holding laptop checks and strips the FC's signatures toward Mission Planner (UDP 14550) and signs Mission Planner's commands toward the FC. It never forwards SETUP_SIGNING. Tested on the real FC with repo clients; Mission Planner itself (1.3.83, now installed on the software laptop) not yet.
- ✅ **Output map set and read back** (23:09, through the proxy): S1 70, S2 0, S3/S4 4, S5 19, S6 21. ⚠️ S1 put out 1500 µs until the FC was rebooted, and S3 kept the old throttle trim (fixed to 1500). After the reboot S1 reads 1100 µs disarmed. **P1 still checks it on screen before the ESC goes on S1.**
- FC checks (USB, indoors): microSD card present and healthy; GPS detected (no fix indoors); compass QMC5883L at I2C 0x0D detected. **RC: 0 channels**, so the XR1 isn't bound yet. Accel and compass not calibrated (tools ready: `scripts/fc_bench.py`).
- From P1 22:51: XR1 wired (TX→R6, RX→T6, 5V→4V5); GPS harness built by function. From P2 22:30: servo bench tester (`tools/servo_bench`), a candidate for ESC-calibration method (a).

*Previous merge (P1 21:02):*
- ✅ **G2 passed** (approximate readings): pack ≈12 V; FC 5V, 4V5, Vx and UBEC output all ≈5 V; no heat.
- The **FC supply rails are healthy** after the wiring incident.
- The **ESC has a BEC** (≈5 V on its plug's middle wire), so its red contact must be lifted before S1.
- XR1 goes on the receiver header's 4V5. The GPS supply waits for the exact 4V5 decimals.
- G1 results were not recorded.
- **M2 starts now:** output map → XR1 → bind → accelerometer calibration → ESC on S1.

*Previous merge (P1 19:48–20:03):* M1.C soldered; the capacitor sits across B+/B−; the ESC is on an XT60 pair; UBEC jumper on 5 V; conflicts raised (Devpost 09:00, GPS supply, Pi ≥ 5.1 V); Pi GND on pin 14 accepted.

**Per-person work plan with checklists: [`docs/WORKPLAN.md`](docs/WORKPLAN.md).**

> 📣 **Open notice for Iain (P1):** [`docs/notices/2026-11-07_1920_for-P1-Iain.md`](docs/notices/2026-11-07_1920_for-P1-Iain.md). It lists every change since his 17:37 review. ⏳ unacknowledged.

**Merged so far:**
- **P1** updates 17:11, 17:31, 17:37, 19:48 (M1.C done; conflicts), 19:53, 20:03, **21:02 (G2 pass)**
- **P2** updates 17:21, 18:30
- **Software / HITL** from the repo:
  - HITL bench test (17:34, `9cd547e`)
  - geofence + FC configuration through the Pi (17:53, `cb18601`)
  - governed autoland at Schuyler: one-sided circuit, approach gate, fenced surveys (19:18, `ed87b68`)
  - local JEV-9B decision model as the default agent ranker (19:18, `9f21d69`)
  - read: `docs/CHECKLIST.md`, `docs/SESSION_LOG.md`, `README.md`, `config/`, `scripts/`
- **P1's sources:** Mission Planner logs (13:50, 14:25) and `docs/hardware/fc/inav_8.0.1_backup_20261107.txt`
- **Still missing:** written updates from **P3** (Pi & camera) and **P4** (FC & radio). Their rows below come from the repo and P1's notes.

> **How this file works.** Each person posts an update in [`docs/updates/`](docs/updates/README.md) using the template. Each merge rewrites this file: gate board, blockers and plan. A gate is ticked only with evidence. Evidence lives in `docs/CHECKLIST.md` (tests) and `config/flight_gates.toml` (flight gates). This file is the cross-team picture. *(Supersedes `docs/hardware/TEAM_STATUS.md` and `progress/`, merged here at H7.0.)* Wiring reference: [`docs/hardware/WIRING.md`](docs/hardware/WIRING.md).

---

## 0 · Headline
- 🎯 **End goal by 11:00 Sunday:** real Tutor flight data in the demo, next to the SITL governed autoland.
  - **F1** FBWA maiden at first light (≈06:35), with the Pi recording.
  - **F2** AUTO survey through the signed uplink (08:00–09:15).
  - Real imagery into the landability map by ≈10:30.
  - Everything (flying + coding) stops at 11:00.
  - **New at 19:18:** a governed autoland now **fits inside the Schuyler fence in SITL** (one-sided circuit). Real F3/F4 becomes a **stretch after F2**, only if F1's measured turn radius is ≤ ~50 m and the team agrees (§5).
- ⏱️ **To fly at ≈06:35, F0 has to pass by ≈04:00.** That means G1 → G5 tonight with almost no slack.
  - **M1.C soldered (19:48) and G2 passed (≈21:00, approximate readings).** Next: **M2**, the output map (P4, Iain checks) → XR1 → bind → accelerometer calibration → ESC on S1 → **G3**. About 30 min behind the plan. This is the critical path.
  - P3 takes over the camera opening (A1); P4 preps the radio, the parameter sheet and the field config (`docs/WORKPLAN.md`).
- ✅ **Software is essentially done.** S1–S3 pass; the S4 SITL flow passes; HITL passes on the real FC (10/10); the fence is set and the audit is 17/17; FC parameters can be changed through the Pi. Governed circuit + stabilized-approach gate fit Schuyler in Tutor-speed SITL; the JEV-9B agent runs locally (template fallback).
- ✈️ **The airframe is built** (P2). Wing fit + layout ≈20:30; surfaces at G3 (≈21:30); install + CG ≈23:30.
- 🔌 **Wiring:** full diagram + connection tables in [`docs/hardware/WIRING.md`](docs/hardware/WIRING.md).
- ⚠️ **Top hazards:**
  - Output map set 23:09 and read back; waiting for P1's on-screen check before the ESC goes on S1. Reboot the FC after any SERVOn_FUNCTION change (S1 kept 1500 µs until a reboot).
  - Possible 4V5 back-feed.
  - The FC can't arm at the bench (fence + no GPS indoors), so ESC calibration and motor direction need the method in §2 #6.
  - Pi pin 6 is double-booked (§2 #7).
- 🟡 **Physical blockers for F1:** the FC won't arm outside the uploaded fence, so **load the flight site's fence**. Plus wind, field clear, roles staffed. Remote ID can't block arming on our firmware (§2 #8).

## 1 · Gate board
### Hardware commissioning (prop off throughout)
| Gate | What it proves | Status | Evidence / note |
|---|---|---|---|
| **G0** | Board identified | ✅ Pass | INAV backup: `INAV/COREWINGF405WMINIV2 8.0.1`. Banner: `ArduPlane V4.7.2 (fb773567)`, `CoreWingF405WMiniV2` |
| — | Firmware + Cloudbreak FC parameters | ✅ Applied | CHECKLIST: param backup 1137/1137, `fc_setup_usb.py` applied (sysid 42, signing, MAV stream rates, FS settings, WP_RADIUS 20). Re-verified through the Pi at 17:46: only intended changes. **Servo outputs not touched** (see §2) |
| — | Geofence on the FC | ✅ Set (bench) | 17:48: Schuyler 21-vertex polygon uploaded and read back identical. FENCE_TYPE 5, ACTION 1 (RTL), ALT_MAX 100 m, RET_ALT 50, OPTIONS 0, ENABLE 1; RTL_ALTITUDE → 50. Not yet checked outdoors with a GPS fix |
| — | Airframe build (P2) | ◐ Built, untested | Fuselage, wing, power pod, gear, skewers done. Motor mounted (not wired). 4 servos installed + linked. Not a gate; feeds G3 (surfaces) and F0 (CG) |
| **G1** | Harness checked cold | ◐ **Not recorded** | M1.C soldered 19:48. The G1 meter results weren't posted before G2. Still to confirm: capacitor polarity (striped leg ≈0 Ω to B−), the ESC XT60 polarity, joint photos |
| **G2** | First power, numbers logged | ✅ **Pass (approx.)** | ≈21:00 (P1). Pack ≈12 V; FC 5V ≈5 V; 4V5 ≈5 V; Vx 5 V; UBEC out ≈5 V; ESC plug middle wire ≈5 V (it has a BEC); no heat at 60 s. `docs/CHECKLIST.md` |
| **G3** | Radio + surfaces correct | ⬜ | Output map **set 23:09** and read back (S1 1100 µs disarmed after a reboot; `docs/CHECKLIST.md`); P1's on-screen check pending. XR1 **bound** (00:00, 16 channels); **radio cal** and **accel cal** done; flight modes + Pocket mode/consent switches set; TX-off failsafe passes on the FC side. Left: surfaces (centring, throws, FBWA then MANUAL directions) and the failsafe with servos + ESC powered. Mission Planner now usable via `scripts/gcs_proxy.py`. Surface work = P2 step A4 |
| **G3b** | GPS + compass + log | ◐ Detected indoors | GPS harness built (P1 22:51). 23:11: GPS detected (no fix indoors), compass QMC5883L at I2C 0x0D, microSD present and healthy. Still to do outdoors: 3D fix, compass calibration (installed), a log |
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
| **D1** Demo assembled + Devpost | ⬜ | ⚠️ HackRPI schedule: Devpost by **09:00**; coding stops 11:00 (conflict with the "optional" wording, see §5) |

### Flight ladder (`config/flight_gates.toml`)
F0 ground checks · F1 maiden · F2 AUTO survey · F3 practice approaches · F4 end-to-end: **all not started.** F0 can't start before G5.
**Targets:** F0 02:30–04:00 Sun · F1 ≈06:35 · F2 08:00–09:15 · real map by ≈10:30 · hard end 11:00 · F3/F4 after the event.

## 2 · Safety flags (read before touching hardware)
1. 🔴 **No ESC on S1 until the output mapping is fixed and P1 has checked it on screen.** Required values:
   - `SERVO1_FUNCTION=70` (ESC)
   - `SERVO2_FUNCTION=0`
   - `SERVO3_FUNCTION=4` (left aileron)
   - `SERVO4_FUNCTION=4` (right aileron)
   - `SERVO5_FUNCTION=19` (elevator)
   - `SERVO6_FUNCTION=21` (rudder)

   **Set 23:09 and read back** (`docs/CHECKLIST.md`). It took a reboot before S1 put out the 1100 µs minimum: until then it still sent 1500 µs, about half throttle. P1 checks the values on screen (`scripts/fc_bench.py outputs` or Mission Planner via `scripts/gcs_proxy.py`) before the ESC goes on S1.
2. 🟠 **Wiring incident on the Pi↔FC link** (CHECKLIST). The FC's **settings** were verified intact through the Pi (17:46). **G2 (≈21:00): the FC 5V and 4V5 supplies both measure ≈5 V, so the supply rails are healthy.** The `POWER_STATUS Vcc = 0` report is a software reading. **TELEM pin 6 (4V5) and pins 2–3 stay taped.** The FC holder owes P1 a short write-up.
3. 🟠 **Every session with the Pi wired to the FC goes through the power marshal (P1)**, the same as USB and battery sessions.
4. The prop stays in its bag. No soldering unless the hardware is COLD. Electronics booting ≠ flight readiness.
5. During USB-only FC sessions, the GPS and the Pi link are unplugged or both boards are powered (the 4V5 pins are live on USB).
6. 🟠 **Fence + arming.** With FENCE_ENABLE=1, the FC refuses to arm outside the Schuyler polygon, and the bench is outside it. Arming also needs every other pre-arm item cleared (RC, accel, compass, GPS home), so indoors isn't possible anyway. **ArduPilot's plane ESC calibration arms the FC**, and so does a motor direction check through the FC. P4 + P1 agree a method before ≈20:30:
   - **(a)** ESC calibration + motor direction with a **servo tester**, if anyone has one: no arming, any time after G2;
   - **(b)** check P1's ESC label photo: if the ESC doesn't need calibrating, only motor direction remains;
   - **(c)** in the outdoor **G3b** slot with a GPS fix, under a temporary fence arrangement P1 approves. Then **re-upload the flight-site fence and re-audit to 17/17 before anything else**.

   - **(d) bench motor run, used 2026-11-08 00:44–00:56 with P1's approval:** `scripts/bench_motor_run.py` saves the originals, sets FENCE_ENABLE 0, ARMING_SKIPCHK 4124 and THR_MAX 40 for one run, arms only in FBWA/MANUAL with the throttle down, disarms on any mode change, RC loss or timeout, then restores (fence last) and re-audits. Prop off. `--restore` recovers from a crash.

   Before flying anywhere, upload that site's fence (`fc_params_pi.py fence --site <key>`).
7. 🟠 **Pi pin 6 is double-booked.** The proven TELEM GND is on Pi pin 6. P1's UBEC→Pi lead was drafted as pin 2 (+5 V) / pin 6 (GND). **Move the UBEC GND to pin 14** (or 9 / 20). The GPIO 5 V pins have no reverse-polarity protection, so meter polarity before plugging in.
8. 🟡 **F1 go/no-go at the field.** Any "no" means no flight:
   - The **flight site's fence is loaded** and the audit is 17/17. The FC physically won't arm outside it.
   - Wind ≤ 5 m/s; field clear.
   - All four flight-card roles staffed, and the pilot ready.

   *Remote ID:* the team handles it, and it can't block arming. ArduPilot only enforces it when OpenDroneID is compiled in, which standard firmware doesn't do, and the CoreWing build doesn't enable it.

## 3 · Workstream status
### Tonight at a glance
| Who | Now → ≈21:30 | Later tonight | Sunday |
|---|---|---|---|
| **P1** Iain (power) | M1.C ✅ · **G2 ✅ (≈21:00)** → **M2**: check the output map on screen → XR1 wired (COLD) → USB for bind/calibration → lift the ESC red contact → ESC on S1 · ESC method with P4 | Map check, XR1, accel cal with P4 → G3 → GPS harness + log card → G4 with P3 → install with Andrew → G3b → G5 → F0 | Power owner (proposed) |
| **P2** Andrew (airframe) | **Soldering M1.C with Iain** (heat-shrink, photos, meter, G2 readings) · hands A1 to P3 | A3 wing fit + approve layout (≈20:30) → **G3** servos (≈21:30) → install + **CG/weight** (≈23:30) → F0 CG + structure | Between-flight inspections · flight role TBD |
| **P3** (Pi & camera, air software) | Zero 2 W swap · UBEC lead re-pinned (pin 2 / pin 14) · **A1 camera opening + mount** · propose the Pi spot · ribbon length to Andrew | **G4** (≈23:00) · recording checked in G5 | Pi recording on F1/F2 · real imagery into core |
| **P4** (FC & radio, ground software) | Pocket model + switches + bind prep · parameter sheet · ESC-calibration method with Iain · flight-site fence + hotspot config · propose receiver/GPS spots | Map + bind + radio/accel cal (≈20:30) → G3 → GPS → G3b → **G5** (governor read-only) → F0 fence audit | Ground operator (proposed) · `sysid.py` · F2 on the governor |

### P1 · Power & integration (power marshal) · Iain — *update 21:02*
- **Done:**
  - G0
  - M1.B
  - **M1.C**: XT60 → B+/B−; capacitor across B+/B−; ESC on an XT60 pair from ESC pads 1; UBEC input → ESC pads 2; UBEC jumper 5 V
  - **G2 ✅** (approximate readings, see the gate board)
- **Now:** M2: output map checked on screen → XR1 (TX→R6, RX→T6, 5V→4V5, GND) → bind and calibrations (P4) → ESC red contact lifted → ESC on S1.
- **To record:** G1 meter results (capacitor polarity, ESC XT60 polarity); joint photos; exact 4V5 decimals (decides the GPS supply).
- **Raised (still open, §5):** Devpost 09:00; GPS supply; Pi ≥ 5.1 V criterion.
- Full detail: [`docs/updates/P1_2026-11-07_2102_G2.md`](docs/updates/P1_2026-11-07_2102_G2.md).

### P2 · Airframe · Andrew — *updates 17:21, 18:30*
- **Done:** Tutor fuselage, wing, power pod, landing gear, wing hold-down skewers. Motor mounted (not wired). 4 servos glued in, horns on and linked.
- **Untested:** motor direction; servo neutral, direction and throw; wing fit; CG; all-up weight.
- **After soldering (≈20:30, no power needed):**
  - A2 bay layout approval (P3/P4 propose spots)
  - A3 wing fit and aileron lead reach to S3/S4
  - A1 camera opening is with P3 tonight
- **Later:**
  - A4 surface setup at G3 (≈21:30)
  - Install, then A5 CG at 57–63 mm and weight (≈23:30–00:30)
  - F0: CG + structural check (A7)
- **Now:** soldering M1.C with Iain; A1 camera opening handed to P3 (`docs/WORKPLAN.md`).
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
| ~~FC is on the Pi/HITL bench~~ | — | — | ✅ Closed: M1.C soldered (19:48) |
| ~~G1 + G2 not done~~ | — | — | ✅ G2 passed ≈21:00 (G1 results still to record) |
| ~~Mission Planner can't connect over USB (21:27)~~ | — | — | ✅ 23:13: signing proxy on the key-holding laptop (`scripts\mission_planner_signed.bat`; MP → UDP 14550). Signing stays on. Use the FC on that laptop's USB for calibrations. MP itself not yet exercised |
| No servo tester confirmed | ESC-calibration method (a) | P1 + P4 | Candidate: P2's UNO Q servo bench tester (`tools/servo_bench`, 22:30). Team decides whether it is used for the ESC, or picks (b)/(c) |
| Output mapping checked on screen | ESC on S1, servo centring, G3 / P2 A4 | P1 | Set + read back 23:09 (software); P1 confirms on screen |
| Wiring-incident details | Clearing the 4V5 back-feed concern | FC holder | Write-up in CHECKLIST + P1 inspection at G2 (4V5 / FC 5 V readings) |
| Pad photo + ESC photo review | Capacitor location; ESC red contact | P1 → AI | Photos sent |
| ~~No receiver bound~~ | — | — | ✅ 00:00: XR1 bound to the Pocket, radio cal written, mode + consent switches mapped |
| Bay layout not agreed | P2 A2 (gluing), install at ≈23:00 | P2 + P1 + P4 | Layout agreed on the dry-fit |
| Camera cable length unknown | P2 A1 final cut | P3 | P3 confirms which Zero ribbon we have |
| Fence blocks arming off-site | ESC calibration + motor direction through the FC | P4 + P1 | Method agreed by ≈20:30 (§2 #6) |
| Flight-site fence | F1 (the FC won't arm outside it) | P4 | Site picked; `config/site_<key>.toml` fence drawn if not Schuyler; uploaded + 17/17 at F0 |
| Pi pin 6 double-booked | G4 | P1 + P3 | UBEC GND moved to pin 14 (§2 #7) |
| No autoland-capable site with a fence | Real governed autoland (F3/F4, after the event) | Team | Anderson Field fence + permission |

## 5 · Decisions
| Decision | Status |
|---|---|
| Pi ↔ FC baud | ✅ **230400** (`SERIAL4_BAUD=230`, Pi `air.toml` matches). Replaces 115200 in the original plan |
| Pi link connector | ✅ TELEM GH1.25: pin 1 GND → Pi pin 6, pin 4 RX4 → Pi pin 8, pin 5 TX4 → Pi pin 10. Pins 2, 3 and 6 taped |
| Output mapping | ⬜ S1 ESC (70), S3/S4 ailerons (4), S5 elevator (19), S6 rudder (21). Set by P4, checked by P1 |
| Capacitor location | ✅ **Across B+ / B−** (P1, 19:53). Polarity meter check at G1 |
| ESC connection | ✅ **XT60 pair**: PDB ESC pair 1 → 14 AWG pigtail → XT60 ↔ ESC (P1, 19:53). `WIRING.md` §1 updated |
| XR1 power pin | ✅ Receiver header **4V5** (≈5 V at G2, above 4.5 V) |
| Pi Zero 2 W swap timing | ⬜ recommend **before G4-on-UBEC**, so the power test uses the real load |
| Camera mount | ⬜ P2 proposes nadir, recessed, foam soft-mount. Confirm with P3 |
| Fence parameters | ✅ Schuyler polygon (21 vertices, 12.3 ha, ≥19 m from buildings), FENCE_TYPE 5, ACTION 1 (RTL), ALT_MAX 100 m, RET_ALT 50, OPTIONS 0; RTL_ALTITUDE 50. Planner/governor margin 20 m inside |
| **Scope: real flight** | ✅ **Plan (Andrew): fly Sunday; hard end 11:00 for flying and coding.** Devpost isn't a blocker. Target: F0 overnight → F1 FBWA maiden at ≈06:35 (now including the turn-radius circles) → F2 AUTO survey 08:00–09:15 → real imagery into core by ≈10:30. Every flight is subject to the go/no-go in §2 #8. **F3/F4 = stretch only (team call at ≈09:15):** the 19:18 circuit pattern fits Schuyler in SITL, but it needs F1's measured turn radius (≤ ~50 m, set in `turn_radius_m`), sysid from the F1 log, F3 practice approaches + a forced go-around, and the governor's F0–F3 gates recorded before any F4. In a westerly wind only eastbound circuits fit; otherwise the pilot lands manually |
| Flight site for F1 | ⬜ The Schuyler fence is on the FC. Any other site needs its fence drawn and uploaded first (the FC won't arm outside it). Legal/airspace items are handled by the team |
| Remote ID | ✅ Team handling. No arming block on our firmware (OpenDroneID isn't compiled in) |
| Flight roles | ⬜ PIC · ground operator · safety observer · power owner, one each (`docs/FLIGHT_CARDS.md`). Proposed: P1 power owner, P4 ground operator |
| ESC calibration method under the fence | ⬜ (a) servo tester · (b) skip if not needed · (c) outdoor G3b slot under P1 (§2 #6). Due ≈20:30 |
| UBEC → Pi pins | ✅ +5 V pin 2, GND **pin 14** (§2 #7). Accepted by P1 at 19:48; P3 re-pins, P1 meters polarity at G4 |
| Rest rota | ⬜ 04:00–05:45, at least 2 awake (attended LiPo charging) |
| ⚠️ **Devpost deadline** (raised by P1, 19:48) | ⬜ **Conflict.** This file and `WORKPLAN.md` say Devpost isn't a deadline. HackRPI's published schedule says "All projects must be on Devpost by 9 AM Sunday". Proposal: hard deadline 09:00 with one named owner who isn't on a flight role; submit a complete entry (SITL video, bench footage, repo) before F2; ask the organizers whether edits are allowed until 11:00 |
| ⚠️ **GPS supply** (raised by P1, 19:48) | ⬜ **Conflict.** `WIRING.md` §5 / `WORKPLAN.md` say VCC → FC 4V5. The original plan was the UBEC 5 V (RMRC rates the module at 5.0 V). Proposal: use 4V5 if it measures ≥ 4.75 V under battery at G2, otherwise the UBEC. P1 decides at G2 |
| ⚠️ **Pi voltage criterion** (raised by P1, 19:48) | ⬜ **Conflict.** `WORKPLAN.md` / `WIRING.md` §9 ask for ≥ 5.1 V at the Pi, but the UBEC's correct setting is 5.0 V (6 V would exceed the Pi's input). Proposal: pass = `get_throttled` 0x0 throughout + ≥ 4.9 V at pins 2/14 under camera load. Fix sag with leads, not a higher setting |

## 6 · Remaining plan — tonight → first flight → 11:00
P1's hardware path, re-baselined at H7.75. Each window starts as soon as the one before it passes; if a step slips, shift everything after it by the same amount. Checklists per person: [`docs/WORKPLAN.md`](docs/WORKPLAN.md).

| Window (H) | Clock | Step | Who |
|---|---|---|---|
| 7.5 – 9.0 | 18:30–20:00 | **M1.C** power-board soldering ✅ done 19:48 (reported) → **G1** cold checks (next) | P1 + P2 |
| 7.5 – 9.5 | 18:30–20:30 | *Parallel:* Zero 2 W swap; UBEC lead re-pinned; **A1 camera opening + mount**; Pi spot proposed | P3 |
| 7.5 – 9.5 | 18:30–20:30 | *Parallel:* Pocket model + switches; bind prep; parameter sheet; ESC-calibration method; flight-site fence + hotspot config; receiver/GPS spots proposed | P4 |
| 9.0 – 10.0 | 20:00–21:00 | **G2** first power ✅ (≈21:00; about 30 min late) | P1 + P2 |
| 9.5 – 10.5 | 20:30–21:30 | Output map (Iain checks on screen) → XR1 wired + bound → radio cal → accel cal (bare stack) → ESC plugged into S1. *Parallel:* A3 wing fit + A2 layout approved | P4 + P1 · P2 |
| 10.5 – 11.5 | 21:30–22:30 | **G3** servos: FC centres, pushrods to neutral, throws, **FBWA then MANUAL** directions, TX-off failsafe | P2 + P4 + P1 |
| 11.5 – 12.0 | 22:30–23:00 | GPS harness by function, indoor detection, **microSD log card in the FC** | P1 + P4 |
| 12.0 – 12.5 | 23:00–23:30 | **G4** Pi Zero on the UBEC (pin 2 / pin 14) + TELEM; ≥5.1 V at the Pi with the camera running | P3 + P1 |
| 12.5 – 13.5 | 23:30–00:30 | **Install in the airframe** per A2 → Calibrate Level → **CG + all-up weight** | P2 + P1 (+ P4) |
| 13.5 – 14.25 | 00:30–01:15 | Outdoors: GPS fix + compass cal → **G3b**. ESC cal + motor direction here if method (c) | P1 + P4 |
| 14.25 – 15.5 | 01:15–02:30 | **G5** integrated bench run (real bridge + governor read-only) | All |
| 15.5 – 17.0 | 02:30–04:00 | **F0 ground checks** → evidence in `config/flight_gates.toml` | All |
| 17.0 – 18.75 | 04:00–05:45 | Rest rota (≥2 awake): attended pack charging, field kit packed | Rota |
| 19.0 – 19.5 | 06:00–06:30 | At the field: fence for the site loaded + 17/17; **go/no-go** (§2 #8) | All |
| 19.6 – 20.25 | ≈06:35–07:15 | **F1** FBWA maiden: hand launch, trim, RTL/LOITER at altitude, **≥3 LOITER circles at 40 m to measure the turn radius**, land. Download the DataFlash log + Pi session | All |
| 20.25 – 21.0 | 07:15–08:00 | Inspect; `sysid.py`; **set `turn_radius_m` from the F1 log**; check the frames; fix trim/CG; record F1 evidence | P4 · P3 · P2 |
| 21.0 – 22.25 | 08:00–09:15 | **F2** AUTO survey at 40 m through the signed uplink (needs F0 + F1 recorded) | All |
| 22.25 – 23.5 | 09:15–10:30 | Real imagery → core map + candidates; demo assembly. **Stretch (team call at 09:15):** F3 practice approaches at Schuyler (low approach, forced go-around, then landings) | P3 + P4 · P1 + P2 |
| 23.5 – 24.0 | 10:30–11:00 | Last landing by 10:45; commit final code, data and evidence | All |
| **24.0** | **11:00** | **Hard end: flying and coding stop** | All |

### Decision points
- **20:30 (H9.5):** G2 not passed → bench-demo fallback (FC USB telemetry + Pi camera on its own supply). A flight becomes unlikely.
- **22:30 (H11.5):** G3 not passed → no flight Sunday; demo = SITL + bench.
- **02:30 (H15.5):** G5 not passed → the team decides between F0 + F1 with FC DataFlash logging only (Pi recording optional), or stopping hardware for demo polish.
- **04:00 (H17):** F0 not passed → no flight.
- **06:30:** go/no-go at the field. Any "no" is final for that slot, with no pressure to fly.
- **Never cut:** human approval · governor · signed, SITL-separated command path · logging · labels on synthetic data · pilot takeover · pre-arm checks.

## 7 · Questions for the next round of updates
- **FC holder (P4?):** short write-up of the wiring incident for Iain.
- **P1:** G1/G2 results + readings? Capacitor location? ESC red contact lifted? GPS supply decision at G2?
- **Team:** Devpost: who owns the 09:00 submission (§5)? Agree the Pi voltage pass criterion (§5).
- **P4:** output map + accel cal done? Pocket EdgeTX/ELRS versions? Which ESC-calibration method (§2 #6)?
- **P3:** which Zero ribbon (length)? Zero 2 W swap done?
- **P2:** motor label; A3 + layout done? CG marks checked against the kit manual?
- **Team:** flight site (decides which fence goes on the FC), flight roles, who's PIC. At ≈09:15: go for the F3 stretch?
- **Software teammate:** your 19:18 commits went to `full-stack` and were merged into `main` at 19:35. Please work on `main` from now on (see `AGENTS.md`).

## 8 · Where things live
| What | Where |
|---|---|
| This combined picture | `STATUS.md` |
| Personal updates + template + who's who | [`docs/updates/`](docs/updates/README.md) |
| Evidence ledger (tests, bench, HITL) | `docs/CHECKLIST.md` |
| Flight gates F0–F4 (governor reads these) | `config/flight_gates.toml` |
| Flight roles, abort drills, go/no-go | `docs/FLIGHT_CARDS.md` |
| Software session log + design decisions | `docs/SESSION_LOG.md`, `docs/sitl_notes.md` |
| Per-person work plan + checklists | [`docs/WORKPLAN.md`](docs/WORKPLAN.md) |
| Wiring diagram + connection tables + remaining-step guides | [`docs/hardware/WIRING.md`](docs/hardware/WIRING.md) |
| FC backups | `docs/hardware/fc/` |

## 9 · Sources
- `docs/updates/P1_2026-11-07_1711_M1B.md`, `P1_2026-11-07_1731.md`, `P1_2026-11-07_1737.md`, `P2_2026-11-07_1721.md`, `P2_2026-11-07_1830.md`
- ArduPilot CoreWingF405WMiniV2 board README (Plane-4.7.2); ArduPilot plane ESC calibration (arming required); ArduPilot OpenDroneID docs (build-time feature)
- Repo `atciamb/cloudbreak` `main`, including `9cd547e` (HITL), `cb18601` (geofence + FC config through the Pi) and `docs/CHECKLIST.md`
- `docs/hardware/fc/inav_8.0.1_backup_20261107.txt`; P1's Mission Planner tlogs (13:50, 14:25)
