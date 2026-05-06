# bt-proximity-lock

**Linux Dynamic Lock via Bluetooth RSSI Delta** — inspired by Windows Dynamic Lock.

Automatically locks your Linux desktop when your phone moves away, using **signal strength delta** (not just presence detection) for accurate and reliable proximity sensing.

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Quantum505Void/bt-proximity-lock/main/install.sh | bash
```

The installer will:
1. Check and install dependencies (`python3-dbus`, `bluez`)
2. List your paired Bluetooth devices and ask for your phone's MAC
3. Download the script to `~/.local/bin/`
4. Create and start a systemd user service (auto-starts on login)

**Uninstall:**
```bash
curl -fsSL https://raw.githubusercontent.com/Quantum505Void/bt-proximity-lock/main/uninstall.sh | bash
```

---

## How it works

```
Startup:  sample RSSI 8 times → establish baseline (e.g. +6 dBm)

Loop every 3s:
  Read RSSI via hcitool → smooth with 5-sample sliding window
  delta = avg_rssi - baseline
  if delta < -10 for 25s → lock screen (dbus → loginctl fallback)
  if device disappears (5 failures) for 25s → lock screen
```

This mirrors how **Windows Dynamic Lock** works internally:
- Establish baseline RSSI when device is nearby
- Lock when signal drops more than a threshold (default -10 dB)
- Delay before locking to avoid false triggers when briefly stepping away

---

## Why different from other tools

| Feature | This project | Most alternatives |
|---|---|---|
| Detection method | **RSSI Delta** (signal change from baseline) | Absolute RSSI or presence-only |
| Baseline | **Dynamic** (sampled at startup) | Static threshold |
| Signal smoothing | **Sliding window** (5 samples) | Single reading |
| Lock trigger | Signal drops **>10 dB** for **25s** | Instant or fixed timeout |
| Screen lock | **dbus** (GNOME/Wayland native) + loginctl fallback | loginctl only |
| Install | **One-line curl** | Manual setup |
| Systemd | **User service** (auto-start on login) | Manual startup |

---

## Configuration

Edit `~/.config/systemd/user/bt-proximity-lock.service`:

```ini
[Service]
Environment=BT_MAC=AA:BB:CC:DD:EE:FF   # Your phone's MAC address
```

Or edit the script directly at `~/.local/bin/bt_proximity_lock.py`:

```python
TARGET_MAC     = ""      # Phone Bluetooth MAC (or set via BT_MAC env)
RSSI_DELTA     = -10     # Lock when signal drops by this much (dB)
LOCK_DELAY     = 25      # Seconds signal must stay low before locking
CHECK_INTERVAL = 3       # Polling interval (seconds)
RSSI_SAMPLES   = 5       # Sliding window size for smoothing
BASELINE_COUNT = 8       # Startup samples to build baseline
```

After editing:
```bash
systemctl --user daemon-reload && systemctl --user restart bt-proximity-lock.service
```

---

## Requirements

- Python 3.8+
- `python3-dbus` (GNOME screen lock via dbus)
- `bluez` (`hcitool rssi`)
- Phone must be **Bluetooth paired** with the computer

---

## Commands

```bash
# View live logs
journalctl --user -u bt-proximity-lock.service -f

# Stop / Start / Restart
systemctl --user stop bt-proximity-lock.service
systemctl --user start bt-proximity-lock.service
systemctl --user restart bt-proximity-lock.service

# Disable auto-start
systemctl --user disable bt-proximity-lock.service
```

---

## Tested on

- Zorin OS 18.1 (Ubuntu 24.04 Noble, GNOME 46, X11)
- Phone: vivo X200 Pro (Android)

---

## License

MIT
