#!/usr/bin/env bash
# Push the air-side code to the Pi and restart services (run from Git Bash on the laptop).
#   scripts/deploy_pi.sh <user@host> [--setup]
set -euo pipefail
TARGET="${1:?usage: deploy_pi.sh user@host [--setup]}"
KEY="${HOME}/.ssh/cloudbreak_pi"
KNOWN_HOSTS="${CB_PI_KNOWN_HOSTS:-${CLOUDBREAK_DATA:-C:\\cb-data}\\keys\\known_hosts_pi}"   # the Pi's host key lives here, not in ~/.ssh
SSH=(ssh -i "$KEY" -o UserKnownHostsFile="$KNOWN_HOSTS" -o StrictHostKeyChecking=accept-new "$TARGET")
cd "$(dirname "$0")/.."
tar --exclude='__pycache__' -czf - cloudbreak/__init__.py cloudbreak/common cloudbreak/air \
  | "${SSH[@]}" 'sudo mkdir -p /opt/cloudbreak/src && sudo tar -xzf - -C /opt/cloudbreak/src && sudo find /opt/cloudbreak/src -name "*.sh" -exec sed -i "s/\r$//" {} +'
if [ "${2:-}" = "--setup" ]; then
  "${SSH[@]}" 'sudo bash /opt/cloudbreak/src/cloudbreak/air/setup_pi.sh'
else
  "${SSH[@]}" 'sudo systemctl restart cloudbreak-mavbridge cloudbreak-capture cloudbreak-frameserver 2>/dev/null || true'
fi
echo "deployed to $TARGET"
