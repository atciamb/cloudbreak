"""Signing proxy so Mission Planner / QGroundControl / repo scripts can operate the signed real FC from this laptop.

    .venv\\Scripts\\python scripts\\gcs_proxy.py                 # FC on USB (auto-detected)
    .venv\\Scripts\\python scripts\\gcs_proxy.py --fc tcp:129.161.144.214:14560   # through the Pi
    .venv\\Scripts\\python scripts\\gcs_proxy.py --read-only     # watch only

Mission Planner: UDP, port 14550. Repo scripts: --port tcp:127.0.0.1:5770. Details: cloudbreak/ground/gcs_proxy.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudbreak.ground.gcs_proxy import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
