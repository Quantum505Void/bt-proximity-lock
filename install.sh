#!/usr/bin/env bash
# install.sh — bt-proximity-lock one-line installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Quantum505Void/bt-proximity-lock/main/install.sh | bash

set -euo pipefail

REPO="Quantum505Void/bt-proximity-lock"
BRANCH="main"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
INSTALL_DIR="$HOME/.local/bin"
SERVICE_DIR="$HOME/.config/systemd/user"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✔${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗${NC}  $*"; exit 1; }
info() { echo -e "${BLUE}→${NC}  $*"; }

echo ""
echo -e "  ${BLUE}bt-proximity-lock${NC} — Linux Dynamic Lock via Bluetooth RSSI Delta"
echo -e "  Inspired by Windows Dynamic Lock"
echo -e "  https://github.com/${REPO}"
echo ""

# ── 1. Python 3 ──────────────────────────────────────────────────────────────
PY=$(command -v python3 || true)
[[ -n "$PY" ]] || err "python3 not found"
ok "Python $("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

# ── 2. 依赖检查 ──────────────────────────────────────────────────────────────
info "Checking dependencies..."
if ! "$PY" -c "import dbus" 2>/dev/null; then
    info "Installing python3-dbus..."
    sudo apt-get install -y python3-dbus --no-install-recommends -q \
        && ok "python3-dbus" || err "Failed to install python3-dbus"
else
    ok "python3-dbus"
fi

if ! command -v hcitool &>/dev/null; then
    info "Installing bluez..."
    sudo apt-get install -y bluez --no-install-recommends -q \
        && ok "bluez (hcitool)" || err "Failed to install bluez"
else
    ok "bluez (hcitool)"
fi

# ── 3. 找手机 MAC ─────────────────────────────────────────────────────────────
BT_MAC=""
if bluetoothctl devices 2>/dev/null | grep -q ":"; then
    echo ""
    info "已配对蓝牙设备："
    bluetoothctl devices 2>/dev/null | while read -r _ mac name; do
        echo "    $mac  $name"
    done
    echo ""
    read -rp "  请输入手机的 MAC 地址（例：E4:57:68:A2:13:02）: " BT_MAC
else
    echo ""
    warn "未找到已配对设备，请先将手机与电脑蓝牙配对"
    read -rp "  输入手机 MAC 地址（留空跳过，稍后手动设置）: " BT_MAC
fi

# ── 4. 下载脚本 ───────────────────────────────────────────────────────────────
info "Downloading bt_proximity_lock.py..."
mkdir -p "$INSTALL_DIR"
curl -fsSL "$RAW/bt_proximity_lock.py" -o "$INSTALL_DIR/bt_proximity_lock.py"
chmod +x "$INSTALL_DIR/bt_proximity_lock.py"
ok "Script → $INSTALL_DIR/bt_proximity_lock.py"

# ── 5. 写入 systemd service ───────────────────────────────────────────────────
info "Installing systemd user service..."
mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_DIR/bt-proximity-lock.service" << EOF
[Unit]
Description=Bluetooth Proximity Lock - Dynamic Lock via RSSI Delta
After=bluetooth.target graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
Environment=BT_MAC=${BT_MAC}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/bt_proximity_lock.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF

ok "Service → $SERVICE_DIR/bt-proximity-lock.service"

# ── 6. 启用服务 ───────────────────────────────────────────────────────────────
systemctl --user daemon-reload

if [[ -n "$BT_MAC" ]]; then
    systemctl --user enable --now bt-proximity-lock.service
    sleep 2
    if systemctl --user is-active --quiet bt-proximity-lock.service; then
        ok "Service started and enabled"
    else
        warn "Service failed to start, check: journalctl --user -u bt-proximity-lock.service"
    fi
else
    systemctl --user enable bt-proximity-lock.service
    warn "MAC not set — edit the service file and set BT_MAC, then:"
    echo "    nano $SERVICE_DIR/bt-proximity-lock.service"
    echo "    systemctl --user daemon-reload && systemctl --user start bt-proximity-lock.service"
fi

# ── 7. l2ping sudoers（如果需要）─────────────────────────────────────────────
# bt_proximity_lock.py 用 hcitool rssi，不需要 sudo，跳过

# ── done ─────────────────────────────────────────────────────────────────────
echo ""
ok "Installation complete!"
echo ""
echo "  查看日志:  journalctl --user -u bt-proximity-lock.service -f"
echo "  停止服务:  systemctl --user stop bt-proximity-lock.service"
echo "  卸载:      curl -fsSL $RAW/uninstall.sh | bash"
echo ""
