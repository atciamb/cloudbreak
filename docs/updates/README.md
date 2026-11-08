# Personal updates

Each person posts short, timestamped updates here. Every update gets merged into the master status, [`STATUS.md`](../../STATUS.md), and its gate board, blockers and plan are rewritten. Updates are snapshots: once posted, they aren't edited. Post a new one instead.

Notices addressed to one person (e.g. "what changed since your last review") live in `docs/notices/`. Agents present open ones first; see `AGENTS.md`.

## Who's who

| ID | Role | Name |
|---|---|---|
| P1 | Power & integration (power marshal) | Iain |
| P2 | Airframe | Andrew |
| P3 | Pi & camera | _add name_ |
| P4 | FC & radio | _add name_ |

Software work (SITL, core, planner, governor, agent, HITL) is logged in the commits and in `docs/CHECKLIST.md`.

## How to post

1. Copy [TEMPLATE.md](TEMPLATE.md) to `P#_YYYY-MM-DD_HHMM.md`. An optional short tag at the end is fine, e.g. `P1_2026-11-07_1711_M1B.md`.
2. Keep it short. Write "none" rather than deleting a section.
3. Only claim a gate if you can point to evidence. Test evidence goes in `docs/CHECKLIST.md`; flight-gate evidence goes in `config/flight_gates.toml`.
4. Commit to `main` (`git pull --rebase` first), or paste the update into chat and whoever merges `STATUS.md` will add it.

## Updates so far

| File | Who | Covers |
|---|---|---|
| [P1_2026-11-07_1711_M1B.md](P1_2026-11-07_1711_M1B.md) | P1 | M1.B off-board power prep; M1.C/G1/G2 plan |
| [P1_2026-11-07_1731.md](P1_2026-11-07_1731.md) | P1 | G0 pass; output-mapping hazard found |
| [P1_2026-11-07_1737.md](P1_2026-11-07_1737.md) | P1 | Waiting for the FC; wiring-incident questions; new marshal rule |
| [P2_2026-11-07_1721.md](P2_2026-11-07_1721.md) | P2 | Tutor built; airframe steps A1–A7 |
| [P2_2026-11-07_1830.md](P2_2026-11-07_1830.md) | P2 | Correction: code freeze 11:00, so plan to fly Sunday; wiring diagram; airframe timeline |
| [P1_2026-11-07_1948_M1C.md](P1_2026-11-07_1948_M1C.md) | P1 | M1.C soldering done; G1/G2 next; conflicts: Devpost 09:00, GPS supply, Pi voltage criterion |

Path note: P1's updates refer to `docs/inav_backup.txt` (P1's local copy). In the repo it's [`docs/hardware/fc/inav_8.0.1_backup_20261107.txt`](../hardware/fc/inav_8.0.1_backup_20261107.txt).
