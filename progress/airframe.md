# Airframe progress: Flite Test Tutor

**Owner:** Andrew Ciambella (airframe)
**Last updated:** Sat 2026-11-07, ~5:45 PM ET (HackRPI day 1; repo at `b36bcaa`)
**Overall:** The mechanical build is basically done. Nothing on the aircraft has been powered yet, so the motor, servos, control surfaces and balance are all **built, untested**.

## Summary

We built the Tutor by following the Flite Test Tutor build videos: fuselage, wing, power pod, landing gear and wing hold-down skewers. The motor is mounted on the power pod. The servos are installed and linked to the control surfaces with pushrods and control horns. The motor isn't wired yet because electronics is still soldering the ESC.

What's left on the airframe is small: cut a downward camera opening, mount the avionics, fit the wing, then (once things are powered) set the control surfaces and check the CG. Those last items are part of flight gate **F0** (`config/flight_gates.toml`).

The software and SITL side is well ahead: a governed SITL autoland runs end to end, and the FC→Pi link has passed on the bench (see `docs/CHECKLIST.md`). So getting the aircraft through F0 is now the main thing between us and a first real flight. That first real flight log is also what `sysid.py` needs to fix the SITL landing overshoot (+71 m past the aim point).

## What's done

| Item | State | Notes |
|---|---|---|
| Fuselage (main Tutor body) | Done | Built per the build video |
| Wing (standard) | Done | Built per the build video |
| Wing hold-down skewers | Done | Bamboo skewers through the fuselage for the rubber bands that hold the wing on |
| Power pod (slide-in motor mount) | Done | Built; slides into the nose |
| Landing gear | Done | Installed |
| Motor | Built, untested | Mounted on the power pod. Not wired to the ESC; has never spun |
| Servos (4: 2× aileron, elevator, rudder) | Built, untested | Installed. Not yet driven by the flight controller |
| Pushrods + control horns | Built, untested | Linked to all surfaces. Neutral position and throws not set yet (needs powered servos) |
| ESC | In progress (electronics) | Being soldered by electronics. Not connected to the motor |

## Built but not yet verified

Built doesn't mean it works (see the README ground rules). None of these have been checked yet:

- **Motor:** never spun, so the spin direction is unknown.
- **Servos and surfaces:** never driven by the FC, so neutral, direction and throw are all unchecked.
- **Wing fit:** the skewers are in, but the wing hasn't been banded on yet to check fit, alignment and servo lead routing.
- **CG and all-up weight:** unknown. These can't be measured until the avionics, Pi, camera and battery are in.

## What's left: airframe workstream

In suggested order. Steps A1–A3 can happen now. A4–A6 need powered electronics.

| # | Task | Depends on | Notes |
|---|---|---|---|
| A1 | **Camera opening and mount** in the fuselage floor, lens pointing straight down | Pi Zero camera cable length (onboard) | The design assumes a nadir camera; the last-look leg exists because a banked plane's nadir camera can't see the strip. Recess the lens so a hard landing can't hit it. Soft-mount on foam to cut motor vibration, because the Camera Module 3 has a rolling shutter and vibration shows up as "jello" in the frames the map depends on. |
| A2 | **Avionics layout and mounting**: FC, receiver, GPS/compass, Pi Zero 2 W, Pi UBEC, battery | Agree the layout with electronics and onboard | FC near the CG, flat, arrow pointing forward (otherwise set `AHRS_ORIENTATION`). GPS/compass on top with a clear sky view, away from the ESC, battery leads and motor (magnetic interference; the FC already reports compass 1 unhealthy on the bench). Receiver antennas clear of wiring and the battery. Battery on velcro plus a strap, with room to slide it for CG. When the bench Pi↔FC wiring moves into the plane, **TELEM pin 6 (4V5) stays disconnected** (`docs/CHECKLIST.md`). |
| A3 | **Wing fit**: band the wing on and check alignment | — | Check the aileron servo leads reach the FC (they may need extensions). Make sure the leads aren't pinched where the wing seats. |
| A4 | **Surface setup** (joint with electronics) | FC driving the servos (receiver bound, outputs assigned) | Let the FC center the servos, then readjust the pushrods so every surface is neutral. Set throws per the Tutor plans/video. **F0 item:** directions correct in MANUAL **and** FBWA. Tilt the plane by hand and the surfaces should push back against the tilt. |
| A5 | **CG and weight** with the full flight load (battery, Pi Zero, camera, UBEC, GPS) | A2 done, everything installed | **F0 item.** Flight cards give **57–63 mm behind the leading edge**; check that against the kit manual. Move the battery first; add nose weight only if you have to. Record the all-up weight here. |
| A6 | **Prop on** only for the final thrust test and flight | Motor direction confirmed (electronics) | Keep the prop **off** for all bench work, including the F0 failsafe test. |
| A7 | **Pre-flight structural check** | A1–A6 | Landing gear secure, hinges and horns glued, power pod seated, wing bands snug, no loose wires near the prop. Feeds into the F0 sign-off. |

## What's left for the whole aircraft

Everything below is owned by other workstreams. It's listed here so this file shows everything between "built" and "flyable". Verified results live in `docs/CHECKLIST.md`.

**Already passed on the bench** (from `docs/CHECKLIST.md`): FC identified as CoreWing F405 Wing Mini V2 on ArduPlane 4.7.2, parameters backed up and Cloudbreak params plus signing applied, FC→Pi UART4 link at 230400 working, Pi camera and frame server working (on the Pi 3).

**Electronics hookup** ([electronics.md](electronics.md))
- Finish the ESC soldering. Connect the ESC to the motor and the battery lead.
- Spin the motor with the prop off and fix the direction if needed (swap any two motor wires).
- Servos and ESC signal on FC outputs. Pi UBEC holds **5.1–5.2 V at the Pi** (under-voltage was seen on the bench).
- Clear the open FC pre-arm items: 3D accel calibration, compass 1 unhealthy, waiting for RC, waiting for home (GPS).
- Follow up the wiring incident: the USB dry run is pending, and the FC reports Vcc = 0.

**Wireless handling**
- **Pilot link:** bind the XR1 Nano receiver to the RadioMaster Pocket (this is the "waiting for RC" pre-arm item). Set up the switches: flight mode FBWA/AUTO/RTL, plus the autonomy-consent switch on RC7. Do the TX-off failsafe test (prop off) and a range check. This link must work on its own, without the Pi or Wi-Fi.
- **Telemetry and uplink:** Pi bridge to the laptop over Wi-Fi; at the field, the Zero joins the field hotspot. Pi→FC (signed uplink) is still untested; that's the HITL bench test.

**Onboard move to the Pi Zero 2 W** ([onboard.md](onboard.md))
- Move the SD card from the Pi 3 to the Zero, swap in the 22-pin Zero camera cable, and set the Wi-Fi to the field hotspot.

**Then F0** (all on the ground): CG, control directions in MANUAL and FBWA, failsafe bench test with the prop off, fence loaded, range check, switches, abort drill.

## Handoffs and interfaces

- **→ Electronics:** I need the FC, receiver and GPS mounting positions agreed before I cut or glue anything (A2). The aileron leads may need extensions. Surface setup (A4) is a joint session as soon as the receiver is bound and the FC drives the servos.
- **→ Onboard (Pi + camera):** the README plans to swap in the 22-pin Pi Zero camera cable (a standard 15-pin cable won't fit the Zero). **Please confirm we have one on hand, and which length** (they come in about 38 mm and 150 mm). The length decides how far the Pi can sit from the camera opening (A1).
- **→ Ground AI:** nothing needed from the airframe for SITL. For real flights, the measured all-up weight and the F1 DataFlash log feed `sysid.py` and the autoland tuning.

## Risks / watch items

- **Daylight and time:** the flight cards list sunset at 16:40 (civil dusk 17:10), and the event ends Sunday afternoon. Any flight this weekend has to be Sunday daylight. So the aircraft should be F0-ready (A1–A7 plus electronics) by Sunday morning.
- **CG shift from the avionics:** the Pi, camera, UBEC and GPS add weight the stock Tutor wasn't balanced for. Check before any flight (A5).
- **Camera vibration:** without soft-mounting, rolling-shutter jello will hurt the imagery the landability map depends on.
- **Compass interference:** compass 1 already reads unhealthy on the bench. Mounting the GPS/compass close to the power leads would make headings worse.
