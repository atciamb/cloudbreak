# Instructions for AI agents working in this repo

These apply to any agent (Claude Code, Codex, Cursor, ChatGPT, etc.) that pulls, reviews or edits Cloudbreak for a team member.

## 1 · First, before any other review output: open notices

1. List `docs/notices/`. A notice is **open** while its `**Status:**` line says `⏳ UNACKNOWLEDGED`.
2. Work out who your user is: run `git config user.email`, or ask.

   | ID | Who | Role | Git identity |
   |---|---|---|---|
   | P1 | Iain | Power & integration (power marshal) | `imackill` · `iain.a.mackillop@gmail.com` |
   | P2 | Andrew | Airframe | `atciamb` · `180782749+atciamb@users.noreply.github.com` |
   | P3 | — | Pi & camera | — |
   | P4 | — | FC & radio | — |

3. **Present every open notice addressed to your user, in full, before anything else.** A summary is acceptable only if it keeps every numbered item. If you can't tell who the user is, list the open notices and ask which applies.
4. When the user has seen it, follow the notice's **Acknowledge** section: flip its Status line, record any response, commit. Don't present an acknowledged notice again.

**Open right now:** [`docs/notices/2026-11-08_0605_for-P2-Andrew.md`](docs/notices/2026-11-08_0605_for-P2-Andrew.md), for **Andrew (P2)**: he takes over the FC / Pi 3 / F2 work from the software laptop (keys to get in person, network for the 2.4 GHz-only Pi 3, open items before F0).

**Also open:** [`docs/notices/2026-11-07_1920_for-P1-Iain.md`](docs/notices/2026-11-07_1920_for-P1-Iain.md), for **Iain (P1)**. His branch was merged and his files moved; the fence is on the FC (bench arming is blocked); his UBEC→Pi lead needs re-pinning; and the plan is now to fly Sunday with an 11:00 hard end.

## 2 · Where things live

| What | Where |
|---|---|
| Master team status: gates, safety flags, blockers, decisions, timeline | [`STATUS.md`](STATUS.md) |
| Per-person checklists to the 11:00 hard end | [`docs/WORKPLAN.md`](docs/WORKPLAN.md) |
| Wiring diagram + connection tables | [`docs/hardware/WIRING.md`](docs/hardware/WIRING.md) |
| Evidence ledger (a test is "passed" only with evidence here) | [`docs/CHECKLIST.md`](docs/CHECKLIST.md) |
| Flight gates F0–F4 (the governor reads these) | [`config/flight_gates.toml`](config/flight_gates.toml) |
| Personal updates (timestamped snapshots) + template | [`docs/updates/`](docs/updates/README.md) |
| Notices to specific people | `docs/notices/` |
| Servo bench tester (UNO Q on D9, no FC needed) | [`tools/servo_bench/`](tools/servo_bench/README.md) |

## 3 · Rules

- **Work on `main`.** Run `git pull --rebase` before pushing. `full-stack` and `hardware-status` are merged and retired.
- **Never mark a gate or test passed without evidence** in `docs/CHECKLIST.md` or `config/flight_gates.toml`.
- Don't edit someone else's update in `docs/updates/`; post a new one. When you merge updates, rewrite `STATUS.md` (gate board, blockers, plan) and say what changed.
- **Safety stays on:**
  - prop off for bench work
  - every power event goes through P1
  - don't weaken pre-arm checks, the fence, MAVLink signing or the governor to get past a failure. The only exception is a procedure written into `STATUS.md` and approved by P1 (e.g. §2 #6 option c), restored and re-audited to 17/17 afterwards
  - keep SITL and real-aircraft command paths separate
  - the "never cut" list in `STATUS.md` §6 holds
- **Hard end: Sunday 11:00, for flying and coding.**
- If something in the repo contradicts `STATUS.md`, treat `STATUS.md` (newest merge) as current and flag the conflict to your user.
