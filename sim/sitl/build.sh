#!/usr/bin/env bash
# Build ArduPlane SITL at the same release as the real flight controller (Plane-4.7.2).
#
# From Windows PowerShell:
#   wsl -d Ubuntu -u root -- bash /mnt/c/dev/cloudbreak/sim/sitl/build.sh deps   # apt packages (root, no sudo prompt)
#   wsl -d Ubuntu          -- bash /mnt/c/dev/cloudbreak/sim/sitl/build.sh build  # clone + python venv + waf build
set -euo pipefail

TAG="${ARDUPILOT_TAG:-Plane-4.7.2}"
AP="${ARDUPILOT_DIR:-$HOME/ardupilot}"
VENV="${ARDUPILOT_VENV:-$HOME/venv-ardupilot}"

case "${1:-build}" in
  deps)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y git build-essential ccache g++ gawk python3-dev python3-pip python3-venv \
      python3-numpy libtool libxml2-dev libxslt1-dev pkg-config rsync
    ;;
  build)
    if [ ! -d "$AP/.git" ]; then
      git clone --branch "$TAG" --depth 1 --recurse-submodules --shallow-submodules \
        https://github.com/ArduPilot/ardupilot.git "$AP"
    fi
    if [ ! -x "$VENV/bin/python" ]; then python3 -m venv "$VENV"; fi
    # shellcheck disable=SC1091
    . "$VENV/bin/activate"
    pip install -q --upgrade pip
    pip install -q "empy==3.3.4" pexpect future lxml pymavlink dronecan setuptools
    cd "$AP"
    git describe --tags --always
    ./waf configure --board sitl
    ./waf plane
    ls -la build/sitl/bin/arduplane
    ;;
  *)
    echo "usage: build.sh deps|build" >&2; exit 2 ;;
esac
