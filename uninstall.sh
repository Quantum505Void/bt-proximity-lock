#!/usr/bin/env bash
# uninstall.sh — bt-proximity-lock uninstaller

set -euo pipefail
GREEN='\033[0;32m'; NC='\033[0m'
ok() { echo -e "${GREEN}✔${NC}  $*"; }

systemctl --user stop bt-proximity-lock.service 2>/dev/null && ok "Service stopped" || true
systemctl --user disable bt-proximity-lock.service 2>/dev/null && ok "Service disabled" || true
rm -f "$HOME/.config/systemd/user/bt-proximity-lock.service" && ok "Service file removed" || true
rm -f "$HOME/.local/bin/bt_proximity_lock.py" && ok "Script removed" || true
systemctl --user daemon-reload

echo ""
ok "bt-proximity-lock uninstalled"
