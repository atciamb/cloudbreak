#!/usr/bin/env bash
# Run ArduPlane SITL (no MAVProxy) homed at RPI '86 Field.
#
# Port map (instance I adds 10*I):
#   SERIAL0 tcp 5760 : held by a local keeper. SITL waits for it at boot and EXITS when it disconnects,
#                      so nothing else may use it. It plays the role of the real FC's USB port.
#   SERIAL1 tcp 5762 : governor (read-write, MAVLink2-signed) -- mirrors the real FC's SERIAL4 via the Pi
#   SERIAL2 tcp 5763 : core (read-only telemetry)
#   SERIAL5 tcp 5765 : QGC / fc_relay (Pi-as-companion dev)
# Env: SITL_INSTANCE, SITL_SPEEDUP, SITL_HOME (lat,lon,alt_msl,hdg), SITL_EXTRA_PARM (extra .parm path(s), comma sep),
#      SITL_WIPE (1 = reset eeprom to defaults), SITL_WORKDIR, SITL_NO_TUTOR (1 = stock defaults only)
set -euo pipefail
AP="${ARDUPILOT_DIR:-$HOME/ardupilot}"
HERE="$(cd "$(dirname "$0")" && pwd)"
I="${SITL_INSTANCE:-0}"
SPEEDUP="${SITL_SPEEDUP:-1}"
HOME_LOC="${SITL_HOME:-42.7303,-73.6798,68,0}"
WORK="${SITL_WORKDIR:-$HOME/sitl-run/$I}"
mkdir -p "$WORK"
cd "$WORK"
DEFAULTS="$AP/Tools/autotest/models/plane.parm"
if [ "${SITL_NO_TUTOR:-0}" != "1" ]; then DEFAULTS="$DEFAULTS,$HERE/tutor_like.parm"; fi
if [ -n "${SITL_EXTRA_PARM:-}" ]; then DEFAULTS="$DEFAULTS,$SITL_EXTRA_PARM"; fi
WIPE=()
if [ "${SITL_WIPE:-1}" = "1" ]; then WIPE=(--wipe); fi
P0=$((5760 + 10 * I))
echo "[run_sitl] instance=$I speedup=$SPEEDUP home=$HOME_LOC ports: keeper=$P0 governor=$((P0 + 2)) core=$((P0 + 3)) relay=$((P0 + 5))"
echo "[run_sitl] defaults=$DEFAULTS"

"$AP/build/sitl/bin/arduplane" -S --model plane --home "$HOME_LOC" --speedup "$SPEEDUP" -I"$I" "${WIPE[@]}" \
  --defaults "$DEFAULTS" --serial5 tcp:5 </dev/null &
SITL_PID=$!

# Hold SERIAL0 for the life of the simulator.
for _ in $(seq 1 100); do
  if exec 3<>"/dev/tcp/127.0.0.1/$P0" 2>/dev/null; then break; fi
  sleep 0.1
done
cat <&3 >/dev/null &
KEEP_PID=$!
cleanup() { kill "$SITL_PID" "$KEEP_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
echo "[run_sitl] keeper attached on $P0 (pid $KEEP_PID); SITL pid $SITL_PID"
wait "$SITL_PID"
