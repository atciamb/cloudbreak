# Ground AI progress: core, planner, governor, agent, SITL, autoland

**Owner:** _TBD (ground AI)_
**Last updated:** _awaiting update_
**Overall:** _awaiting update_

> **Repo state, pre-filled** from `docs/CHECKLIST.md` and `docs/SESSION_LOG.md` (`b36bcaa`) so updates line up. The owner should correct it and fill in the rest. Status words are in [TEMPLATE.md](TEMPLATE.md).

## Repo state so far

| Item | State | Source |
|---|---|---|
| Unit tests | Done (passed) | CHECKLIST |
| ArduPlane 4.7.2 SITL build + verification (signing, read-back hash, hold, failsafes, commit, go-around, aborts) | Done (passed) | `docs/sitl_notes.md` |
| Priors (ortho, LiDAR, DEM, OSM, FAA, weather) | Done (passed) | CHECKLIST |
| Governor: refusals, OTP approval, signed upload + read-back, execution | Done (passed in SITL) | CHECKLIST |
| End-to-end SITL landing via the governor | Flow passed; **accuracy not acceptable** (+71 m past the aim point) | CHECKLIST |
| Local LLM agent (Ollama qwen3:4b), proposals only | Done (runs; schema-checked) | CHECKLIST |
| Autoland BO in SITL | Ran; not validated on held-out conditions | CHECKLIST |
| Safety thresholds | Calibrated on SITL synthetic only; **redo on labelled real frames before flight** | CHECKLIST |
| Real-image segmenter | Works on a real ortho crop; fails on synthetic renders (oracle perception used in SITL) | CHECKLIST |
| Sysid + re-tune from the real Tutor log | Blocked (needs F1) | CHECKLIST |

## Summary

_Owner to fill in._

## Left to do

_Owner to fill in (order, dependencies)._

## Handoffs and interfaces

- **→ Airframe / electronics:** the real Tutor's all-up weight and F1 DataFlash log for `sysid.py`.
- **→ Onboard:** real labelled frames for threshold recalibration.

## Risks / watch items

_Owner to fill in._
