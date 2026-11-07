#!/usr/bin/env bash
# SITL TEST AUTOMATION ONLY: plays the human operator by reading the one-time code from the governor's
# console log. In a real demo/flight a person reads the code off the governor window and types it.
#   scripts/sitl_operator.sh <governor-console-log> survey <idx>
#   scripts/sitl_operator.sh <governor-console-log> land <candidate_id>
#   scripts/sitl_operator.sh <governor-console-log> commit
set -euo pipefail
LOG="$1"; ACTION="$2"; ARG="${3:-}"
PY=/c/dev/cloudbreak/.venv/Scripts/python.exe
case "$ACTION" in
  survey) curl -s -X POST http://127.0.0.1:8700/api/action/request_survey -H "Content-Type: application/json" -d "{\"idx\":$ARG,\"sitl_takeoff\":false,\"alt_m\":45}" >/dev/null; WORD=FLY ;;
  land)   curl -s -X POST http://127.0.0.1:8700/api/action/request_approval -H "Content-Type: application/json" -d "{\"candidate_id\":\"$ARG\"}" | head -c 300; echo; WORD=LAND ;;
  commit) curl -s -X POST http://127.0.0.1:8710/api/commit; echo; exit 0 ;;
esac
sleep 1
OTP=$(grep -o "ONE-TIME CODE:  [0-9]*" "$LOG" | tail -1 | awk '{print $3}')
H=$(curl -s http://127.0.0.1:8710/api/status | $PY -c "import json,sys; print(json.load(sys.stdin)['prepared']['hash'])")
curl -s -X POST http://127.0.0.1:8710/api/approve -H "Content-Type: application/json" \
  -d "{\"mission_hash\":\"$H\",\"otp\":\"$OTP\",\"confirm\":\"$WORD ${H:0:4}\",\"operator\":\"sitl-test\"}"; echo
curl -s -X POST http://127.0.0.1:8710/api/execute | head -c 600; echo
