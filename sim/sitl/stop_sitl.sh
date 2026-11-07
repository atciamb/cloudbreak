#!/usr/bin/env bash
# Stop all SITL instances (exact process-name match, so this script never matches itself).
pkill -x arduplane 2>/dev/null || true
sleep 0.5
pgrep -x arduplane >/dev/null && echo "arduplane still running" || echo "SITL stopped"
