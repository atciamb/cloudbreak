# Team progress

Each workstream keeps one progress file in this folder: what's done, what's left and what it needs from the others. When all four are in, we combine them into the board below and lay out the remaining plan.

This folder doesn't replace [`docs/CHECKLIST.md`](../docs/CHECKLIST.md). The checklist is the verification record: something is **passed** only with evidence there. Progress files are each person's working status and next steps, and they link to checklist rows rather than copying evidence.

## How to post your update

1. Open your file from the table below. Electronics, onboard and ground AI start with the repo state already summarised from `docs/CHECKLIST.md`. Correct anything that's wrong, then fill in the owner sections.
2. Use the status words from [TEMPLATE.md](TEMPLATE.md). If you ran a test, put the evidence in `docs/CHECKLIST.md` and link to it.
3. Fill in the owner and timestamp, then commit and push (`git pull --rebase` first), or open a PR.
4. Mark your row below as submitted.

## Workstreams

| Workstream | Owner | File | Update |
|---|---|---|---|
| Airframe (Tutor build, mounting, surfaces, CG) | Andrew | [airframe.md](airframe.md) | ✅ Submitted Sat 11/7, ~5:45 PM |
| Electronics (power, ESC/motor, FC, radio, GPS) | _TBD_ | [electronics.md](electronics.md) | ⏳ Awaiting |
| Onboard (Pi + Camera Module 3, air services) | _TBD_ | [onboard.md](onboard.md) | ⏳ Awaiting |
| Ground AI (core, planner, governor, agent, SITL, autoland) | _TBD_ | [ground-ai.md](ground-ai.md) | ⏳ Awaiting |

## Where we are (combined)

_Partial: the airframe update plus the repo state at `b36bcaa`. Finish this once every row above says submitted._

| Area | State | Source |
|---|---|---|
| Software + SITL | End-to-end governed SITL autoland works (flow passed). Landing accuracy not acceptable yet (+71 m past the aim point), because the SITL airframe isn't a Tutor. Unit tests pass | `docs/CHECKLIST.md`, `docs/sitl_notes.md` |
| Onboard (bench, Pi 3) | Camera, frame server and MAVLink bridge running; frames geotagged against SITL. Not yet moved to the Pi Zero 2 W | `docs/CHECKLIST.md` |
| FC + link (bench) | FC identified, ArduPlane 4.7.2, params + signing applied. FC→Pi UART4 passed. Pi→FC (signed uplink, HITL) not tested | `docs/CHECKLIST.md` |
| FC pre-arm | Open: 3D accel cal, compass 1 unhealthy, waiting for RC, waiting for home | `docs/CHECKLIST.md` |
| Airframe | Mechanical build done. Camera opening, avionics mounting, wing fit, surface setup and CG left | [airframe.md](airframe.md) |
| Power / ESC / motor | ESC being soldered; motor not connected; never spun | [airframe.md](airframe.md) |
| Pilot radio | Receiver not bound yet (the "waiting for RC" item) | `docs/CHECKLIST.md` |
| Flight gates F0–F4 | None started | `config/flight_gates.toml` |

## Open decisions to settle when we combine

1. **Are we flying this weekend?** Daylight ends around 16:40, and the event ends Sunday afternoon (MLH listing: Sun 11/8, 4 PM). F1 would have to be Sunday morning, which means F0 has to be ready first thing.
2. **Site and permission:** Anderson Field is the only campus site that passes the autoland clearance checks. '86 Field doesn't. Schuyler Flatts needs LAANC and Remote ID. Field use is being arranged through the RPI Aeromodeling Club.
3. **Flight roles** (`docs/FLIGHT_CARDS.md`): pilot (PIC), ground operator, safety observer, power owner. That's one person each, so all four of us.
4. **Submission cutoff:** confirm the real project-submission deadline and write it here: `____`.

## Remaining plan

_To be written once all updates are in._ Draft order to start from:

1. **Tonight, in parallel:**
   - **Electronics:** ESC done → motor spin test (prop off) → receiver bound → accel/compass cal → pre-arm clear.
   - **Airframe:** A1–A3 (camera opening, avionics layout, wing fit).
   - **Onboard:** Pi Zero 2 W swap (SD card, 22-pin camera cable, field Wi-Fi).
2. **Integrate in the airframe:** mount everything, then surface setup (A4) and CG (A5).
3. **HITL bench test** (props off): signed upload and read-back through the Pi; unsigned commands ignored.
4. **F0 ground checks.** Record evidence in `config/flight_gates.toml`.
5. **Sunday daylight, if go:** F1 FBWA maiden with recording. The log goes to `sysid.py` and autoland re-tuning before any F3/F4.
6. **Demo either way:** the SITL end-to-end flow, plus live bench camera and telemetry from the real aircraft. Label synthetic inputs.
