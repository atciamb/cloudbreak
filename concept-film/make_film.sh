#!/bin/bash
# One-command build of the Cloudbreak concept film. Resumable: re-run after an interruption and
# finished shots are skipped. Full render on a 2-core CPU with SwiftShader is ~2.5-3 h; with
# FILM_GPU=1 on a machine with a GPU it is much faster.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

echo "== 1/6 mission trajectory"   && $PY path.py
echo "== 2/6 world + textures"     && $PY assets.py
echo "== 3/6 three.js"             && (cd web && npm install --no-audit --no-fund)
echo "== 4/6 render shots"         && $PY render.py
echo "== 5/6 credits + soundtrack" && $PY credits_render.py && $PY audio.py
echo "== 6/6 grade + mux"          && bash assemble.sh
echo "Done: out/Cloudbreak_Concept_Film.mp4 and out/Cloudbreak_Concept_Film_web.mp4"
