# Work plan — tonight → 11:00 Sunday

**Drafted Sat 11/7 18:45 (≈H7.75).** **Hard end Sun 11:00: flying and coding both stop.** Devpost isn't a deadline or a blocker; do it whenever there's slack. ⚠️ *Conflict raised by P1 (19:48): HackRPI's published schedule says projects must be on Devpost by **09:00 Sunday**. See `STATUS.md` §5.*

**Goal:** real Tutor flight data in the demo, next to the SITL governed autoland:
- F0 ground checks overnight
- **F1** FBWA maiden at first light (≈06:35), with the Pi recording
- **F2** AUTO survey through the signed uplink
- real imagery into the landability map, all by 11:00

**References:**
- Wiring: [`docs/hardware/WIRING.md`](hardware/WIRING.md)
- Gates, flags, decisions: [`STATUS.md`](../STATUS.md)
- Flight roles and drills: [`docs/FLIGHT_CARDS.md`](FLIGHT_CARDS.md)

**Rules that apply to everyone:** prop off for every bench session · P1 runs every power event (USB, battery, Pi wired to FC) · tested = evidence in `docs/CHECKLIST.md` · post short updates in `docs/updates/`.

---

## Right now: M1.C power-board soldering (Iain + Andrew)

Hardware COLD: no LiPo, no USB. All of these go on the **PDB (power board)**, not the FC board. If the PDB connector lets the boards separate, solder the PDB on its own, away from the FC.

- [ ] **P10 first:** check the ESC plug photo, then lift the ESC's red (BEC) contact out of its plug and insulate it.
- [ ] Choose the capacitor location and circle it in P1's update: middle ESC pads, or short twisted 22 AWG leads to B+/B−. Before using the middle pads, meter **ESC+ → B+** and **ESC− → B−**; both should read ≈ 0 Ω.
- [ ] Solder in this order (pre-tin the pad and the wire, plenty of heat and flux, hold still until the joint sets, heat-shrink on before soldering where it applies):
  1. XT60 lead → **B+ / B−** (opposite ends of the board)
  2. 470 µF 35 V capacitor: stripe (−) to negative; sleeve each leg; glue the body down
  3. ESC thick leads → **ESC+ / ESC−** pair 1 (don't cut the + lead short)
  4. UBEC input → **ESC+ / ESC−** pair 2 (leave the UBEC output disconnected)
  5. Inspect, clean the flux, heat-shrink, **photograph every joint**
- [ ] **G1 cold checks** (meter, no battery):
  - [ ] Resistance across the XT60 climbs as the capacitor charges, rather than sitting at ≈ 0 Ω
  - [ ] Continuity on every joint
  - [ ] Pack XT60 polarity matches the aircraft lead
  - [ ] No short across the UBEC output, and the UBEC output isn't connected to FC 5 V / 4V5 / Vx
- [ ] **G2 first power** (Iain powers up; Andrew writes down the numbers): only the FC stack, the ESC (prop off, signal plug **unplugged**) and the UBEC, no load. Log the readings in [`WIRING.md` §9](hardware/WIRING.md#9--readings-to-log-at-g2-p1):

  | Rail | Expected |
  |---|---|
  | Pack | record |
  | FC 5 V pad | 5.2 ± 0.1 V |
  | 4V5 | 4.5–5.0 V |
  | Vx | 5.0 ± 0.1 V |
  | UBEC output | ≈ 5.0 V |
  | Anything warm at 60 s? | no |

  The 4V5 and 5 V readings also settle the wiring-incident question.

---

## P1 · Iain — power & integration (power marshal)

**Tonight**
- [ ] M1.C → G1 → **G2 by ≈20:30** (above). Post the readings.
- [ ] 20:30–21:30, power events for P4 (USB or battery, prop off):
  - output map set
  - XR1 wired to the ELRS header (`RX→T6`, `TX→R6`, `5V→4V5`, `GND→GND`)
  - bind
  - radio calibration
  - accelerometer calibration
- [ ] **Check the output map on screen** (`SERVO1_FUNCTION=70`, 2 = 0, 3 and 4 = 4, 5 = 19, 6 = 21) **before** the ESC signal plug goes on S1.
- [ ] Agree the ESC-calibration / motor-direction method with P4 (§ P4 below). Approve it before anyone arms.
- [ ] 21:30–22:30 **G3** with Andrew + P4: servos powered for centring and the direction checks; TX-off failsafe, prop off.
- [ ] 22:30–23:00: GPS harness **by function** (`TX→RX5`, `RX→TX5`, `VCC→4V5` ⬜ *or UBEC 5 V, decided at G2 (STATUS §5)*, `GND`, `SCL`, `SDA`), continuity on each wire, indoor detection. **microSD card in the FC**: the DataFlash log is what `sysid.py` needs from F1.
- [ ] 23:00–23:30 **G4** with P3: Pi on the UBEC (+5 V **pin 2**, GND **pin 14**, not pin 6) plus TELEM (pins 6/8/10). Meter the Pi pins with the camera running (⬜ proposed pass: `get_throttled` 0x0 and ≥ 4.9 V; never raise the UBEC above 5 V, see STATUS §5).
- [ ] 23:30–00:30: install wiring with Andrew. TELEM pins 2, 3, 6 stay taped; tidy every wire away from the prop arc.
- [ ] 00:30–01:15 **G3b** outdoors with P4: GPS fix, compass calibration; ESC calibration + motor direction there, if that's the method chosen.
- [ ] 01:15–02:30 **G5** integrated run; 02:30–04:00 **F0** (TX-off failsafe, abort drill; you run power).
- [ ] 04:00–05:45: attended LiPo charging (never unattended; LiPo bag), field kit.

**Sunday:** power owner at the field (proposed) · only you connect and disconnect the flight pack · pack voltage logged before and after each flight.

---

## P2 · Andrew — airframe

**Tonight**
- [ ] Now: M1.C with Iain (heat-shrink ready, hold leads, photograph joints, run the meter for G1, write down the G2 numbers).
- [ ] Hand **A1 (camera opening)** to P3 while you solder. Spec: in the fuselage floor, lens pointing straight down, recessed so a hard landing can't hit it, foam soft-mount, positioned so the ribbon reaches the Pi.
- [ ] ≈20:30 **A3 wing fit**: band the wing on, check alignment, check the aileron leads reach **S3/S4** (add extensions if not), no pinched leads.
- [ ] ≈20:30 **A2 layout**: approve P3's Pi/camera spot and P4's receiver/GPS spots:
  - FC near the CG, flat, arrow forward
  - GPS on top, away from the ESC / battery leads / motor
  - receiver antennas clear
  - battery on velcro + strap with room to slide

  No glue until it's agreed.
- [ ] Read the **motor label**; mark the **CG range (57–63 mm behind the leading edge)** on the wing; check it against the kit manual.
- [ ] 21:30–22:30 **G3** with P4 + Iain:
  - [ ] FC powered, MANUAL, sticks centred → servos centred → **reset each pushrod so its surface is neutral**
  - [ ] Throws per the Tutor plans/video
  - [ ] **FBWA first:** tilt and pitch the plane by hand; each surface must push back against the motion. Fix a wrong one with `SERVOn_REVERSED`. Then check stick directions in MANUAL ([ArduPilot four-channel guide](https://ardupilot.org/plane/docs/guide-four-channel-plane.html))
- [ ] 23:30–00:30 **install** with Iain, per the A2 layout. Then **"Calibrate Level"** with the plane at flying attitude (P4 runs it).
- [ ] **CG** at 57–63 mm with the full flight load (move the battery first; nose weight only if needed). **Weigh the all-up weight.** Record both in `docs/CHECKLIST.md`.
- [ ] 02:30–04:00 **F0:** CG + structural check (gear, hinges, horns, power pod seated, wing bands, no wires near the prop) + direction sign-off.

**Sunday:** inspect between flights (prop, gear, hinges, CG unchanged) · flight role TBD · demo footage / Devpost if there's slack.

---

## P3 — Pi & camera (air software)

**Tonight**
- [ ] **Zero 2 W swap:**
  - [ ] Shut the Pi 3 down cleanly, then move the SD card to the Zero
  - [ ] Fit the **22-pin Zero ribbon** to Camera Module 3; `rpicam-hello --list-cameras` sees the IMX708
  - [ ] Add the field-hotspot Wi-Fi profile (keep the campus one); note the Zero's hotspot IP for P4
  - [ ] Services up (capture, frameserver, mavbridge); `free -m` headroom on 512 MB. If it's tight, disable the extras listed in `docs/SESSION_LOG.md` (pipewire, cups, ModemManager, rpi-connectd)
- [ ] **UBEC → Pi lead:** re-pin to +5 V **pin 2**, GND **pin 14** (pin 6 is the TELEM ground). Label it; meter polarity (GPIO 5 V has no protection).
- [ ] **A1 camera opening + mount** (from Andrew's spec): nadir, recessed, foam. **Tell Andrew the ribbon length** and propose where the Pi sits.
- [ ] 23:00–23:30 **G4** with Iain: Pi on the UBEC + TELEM; ≥ 5.1 V at the pins under camera load; bridge gets heartbeats from the real FC; frames geotagged with real pose.
- [ ] G5: confirm a Pi session records frames + pose end to end; check exposure, blur and jello on a few frames.

**Sunday:**
- Start and check Pi recording before each flight.
- After F1/F2, pull the session.
- **Real imagery into core** (real perception, labelled real vs synthetic) → landability map + candidates for the demo by ≈10:30.

---

## P4 — FC & radio (ground software)

**Now** (the FC is on the soldering bench)
- [ ] **Pocket:**
  - [ ] Cloudbreak model, internal ELRS, CRSF, AETR order
  - [ ] **No TX trims**
  - [ ] Check that the ELRS versions on the Pocket and the XR1 match (3.x)
  - [ ] Choose bind-phrase or 3× power-cycle binding ([ExpressLRS binding](https://www.expresslrs.org/quick-start/binding/))
- [ ] **Switches:**
  - [ ] A 3-position switch on the mode channel; a 2-position switch on **CH7** = autonomy consent. The governor reads RC7 > 1700 µs; ELRS high ≈ 2012
  - [ ] The flight cards also want MANUAL (F0 check) and LOITER (F1 switching): mix a second switch into the mode channel, or select them from Mission Planner
- [ ] **Parameter sheet** to enter after G2 in Mission Planner, with Iain watching:

  | Param | Value | Why |
  |---|---|---|
  | `SERVO1_FUNCTION` | 70 | ESC (throttle) |
  | `SERVO2_FUNCTION` | 0 | empty (shares PWM group 1 with the ESC) |
  | `SERVO3_FUNCTION` / `SERVO4_FUNCTION` | 4 / 4 | ailerons |
  | `SERVO5_FUNCTION` | 19 | elevator |
  | `SERVO6_FUNCTION` | 21 | rudder |
  | `FLTMODE_CH` | channel of the 3-position switch | default 8 |
  | `FLTMODE1` | 5 = FBWA | switch low (≤ 1230 µs) |
  | `FLTMODE4` | 10 = AUTO | switch middle (1491–1620 µs) |
  | `FLTMODE6` | 11 = RTL | switch high (≥ 1750 µs) |
  | `RC7_OPTION` | 0 | consent switch does nothing on the FC itself |
  | `SERIAL6_PROTOCOL` | 23 (check) | ELRS / CRSF, board default |
  | `SERVO_AUTO_TRIM` | 1 (optional) | trims itself in FBWA ([ArduPilot takeoff page](https://ardupilot.org/plane/docs/takeoff-landingpage.html)) |

- [ ] **ESC-calibration method** (agree it with Iain before ≈20:30). Plane ESC calibration and a motor check through the FC both **arm** it, and the FC can't arm at the bench (fence, and no GPS indoors). In order of preference:
  - **(a)** a **servo tester**, if anyone has one: no arming, can be done any time after G2;
  - **(b)** if the ESC (from P1's label photo) doesn't need calibrating, only motor direction is left;
  - **(c)** in the outdoor **G3b** slot with a GPS fix, under a temporary fence arrangement P1 approves. Then **re-upload the flight-site fence and re-audit to 17/17** before anything else.
- [ ] **Field config:**
  - [ ] Flight site picked. The FC **won't arm outside the uploaded fence**, so a site other than Schuyler needs its `config/site_<key>.toml` `[fence]` drawn tonight
  - [ ] Field laptop: `set CLOUDBREAK_PI_HOST=<Zero's Wi-Fi IP>` (`config/targets.toml` now reads it; bench default 169.254.77.2)
  - [ ] Field laptop runs core + governor
- [ ] Propose receiver + GPS mounting spots for Andrew's A2.

**Tonight, on the FC**
- [ ] 20:30–21:30: parameter sheet → **bind** → **radio calibration** ([RC systems](https://ardupilot.org/plane/docs/common-rc-systems.html)) → **accelerometer calibration**, bare stack ([guide](https://ardupilot.org/plane/docs/common-accelerometer-calibration.html)). ESC on S1 only after Iain checks the map.
- [ ] 21:30–22:30 **G3** with Andrew + Iain; 22:30 GPS detection; 00:30 **G3b** compass calibration outdoors ([guide](https://ardupilot.org/copter/docs/common-compass-calibration-in-mission-planner.html)); "Calibrate Level" after install.
- [ ] 01:15–02:30 **G5:** real bridge + governor in read-only/telemetry mode against the real FC.
- [ ] **F0:** flight-site fence uploaded + `fc_params_pi.py audit` 17/17; HITL bench re-run; switches; abort drill; record evidence in `config/flight_gates.toml`.

**Sunday:**
- Ground operator on the governor page (proposed).
- `sysid.py` on the F1 DataFlash log; **median LOITER radius from F1 → `turn_radius_m`** in `config/aircraft_tutor.toml` (the circuit and survey turns are sized from it; above ~50 m no governed landing fits Schuyler).
- Stretch, team call at 09:15: F3 practice approaches.
- F2: survey nomination → `FLY` code → Execute; the pilot switches to AUTO at height.

---

## Whole team

**F0 (02:30–04:00):** CG · MANUAL + FBWA directions · TX-off failsafe (prop off) · flight-site fence loaded + 17/17 · range check (ELRS: drop TX power to minimum in the Lua script, walk off, surfaces still respond, then restore it) · switches · abort drill (`docs/FLIGHT_CARDS.md`). Record the evidence in `config/flight_gates.toml`.

**Sunday timeline (hard end 11:00):**

| Clock | Step |
|---|---|
| 05:45 | Pack: plane, charged packs (LiPo bag), Pocket, field laptop, phone hotspot, spare props, tape, velcro, servo tester, meter |
| 06:00–06:30 | Field setup; fence for this site loaded + audit 17/17; **go/no-go**: wind ≤ 5 m/s, field clear, four roles staffed, pilot ready |
| ≈06:35–07:15 | **F1** FBWA maiden: hand launch at full throttle, wings level; climb, trim; RTL / LOITER in and out at altitude; **≥3 LOITER circles at 40 m (turn radius)**; land. Download the DataFlash log + Pi session |
| 07:15–08:00 | Inspect; `sysid.py`; check the frames; fix trim/CG; record F1 evidence |
| 08:00–09:15 | **F2** AUTO survey at 40 m through the signed uplink (needs F0 + F1 recorded) |
| 09:15–10:30 | Real imagery → core map + candidates; demo assembly (SITL autoland run + flight footage + real map). **Stretch (team call):** F3 practice approaches at Schuyler |
| 10:30–11:00 | Last landing by 10:45; commit final code, data and evidence |
| **11:00** | **Everything stops: flying and coding** |

**Decision points:**
- 20:30 no G2 → bench-demo fallback.
- 22:30 no G3 → no flight.
- 02:30 no G5 → team call: F1 on DataFlash only, or stop.
- 04:00 no F0 → no flight.
- 06:30 go/no-go is final for that slot.

**Never cut:** human approval · governor · signed, SITL-separated command path · logging · labels on synthetic data · pilot takeover · pre-arm checks.

**Where Claude can help:** send it the pad/ESC/capacitor photos, the G2 readings, parameter screenshots, error messages or logs (Cloudbreak project chat). It can check them against this plan, run `sysid.py` and the log reviews, draft the Devpost text, and keep `STATUS.md` merged as updates come in.
