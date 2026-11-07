# Cloudbreak flight cards (Tutor, learning pilot)

Read these aloud before each gate. The governor enforces gate order through `config/flight_gates.toml`. That file is edited **only** after a gate passes, with evidence: a log file, a video and initials.

## Roles (one person per role)
- **Pilot (PIC):** holds the Pocket and calls every mode change. They may abort at any time without asking anyone.
- **Ground operator:** works the governor page and reads the one-time code. Never on the radio.
- **Safety observer:** watches the aircraft, airspace, people and the field edge, and calls "ABORT".
- **Power owner:** the only person who connects or disconnects the flight battery.

## Pocket switches (set during F0)
- **Flight mode switch:** FBWA (default) / AUTO / RTL.
- **Autonomy-consent switch (RC7):** must be ON before the governor will commit a landing.
- **Arming:** by the pilot only. The ground never arms the aircraft.

## Abort drills (practise on the ground at F0, then in the air at F1)
1. **Throttle stick to full** during an automatic landing gives a go-around (`LAND_ABORT_THR=1`).
2. **Mode switch to FBWA**: the pilot flies it, wings level and self-levelling.
3. **Mode switch to RTL**: the plane returns home and circles at 50 m.
4. **Operator:** the governor page has an Abort / go-around button. It does nothing if the link is down, so don't rely on it.

## Go / no-go (every flight)
- [ ] Wind ≤ 5 m/s sustained; gusts reviewed (core UI wind panel and METAR KALB)
- [ ] Field clear of people; observer in position; site use approved by the team
- [ ] Battery charged and balanced; CG 57–63 mm behind the leading edge (verify against the kit manual)
- [ ] Control directions correct in MANUAL **and** FBWA (stabilisation corrects the right way)
- [ ] TX-off failsafe tested on the bench, prop off
- [ ] Fence loaded and enabled for THIS site; RTL altitude 50 m (`scripts/fc_params_pi.py audit --site <key>` shows 0 differences and the right vertex count)
- [ ] Pi recording (`/status` shows frames and the bridge); governor shows target **REAL** in red, sysid 42
- [ ] Daylight: sunset 16:40, civil dusk 17:10 (7 Nov) · sunrise ≈06:35 (8 Nov)
- [ ] Fence for THIS site uploaded (the FC won't arm outside it)

## F1: maiden flight (FBWA)
Hand launch in FBWA at full throttle with wings level. Climb to 40–60 m and trim. Check that RTL and LOITER switch in and out cleanly at altitude. Land in FBWA. Download the DataFlash log and the Pi session for `sysid.py`.

## F2: AUTO survey
Ground operator: core UI → survey nomination → governor page: code + `FLY xxxx` → Execute. The governor uploads and verifies the mission. The pilot flips the switch to AUTO once the plane is at survey height. The pilot takes over in FBWA if anything looks wrong.

## F3: practice approaches
Use a hand-designated strip with learned parameters. First fly a low approach: abort at about 8 m with the throttle stick. Then do full landings. Record every touchdown point; they become the real dispersion data.

## F4: Cloudbreak end-to-end
Survey → map → candidates → proposal → **Request approval** → governor code + `LAND xxxx` → **Execute** (plane goes to the hold) → the last look gets at least 3 views → consent switch ON → **Commit** → autoland.

The pilot's thumb stays on the throttle the whole time.
