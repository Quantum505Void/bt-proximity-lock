# bt-proximity-lock

**Linux Dynamic Lock via Bluetooth RSSI Delta** — inspired by Windows Hello Dynamic Lock.

Automatically locks your Linux desktop when your phone moves away, using **signal strength delta** (not just presence detection) for accurate and reliable proximity sensing.

## Why different from other tools?

| Feature | This project | Most alternatives |
|---|---|---|
| Detection method | **RSSI Delta** (signal change) | Absolute RSSI or presence-only |
| Baseline | **Dynamic** (sampled at startup) | Static threshold |
| Signal smoothing | **Sliding window** (5 samples) | Single reading |
| Lock trigger | Signal drops **> 10dB** for **25s** | Instant or fixed timeout |
| Screen lock | **dbus** (GNOME/Wayland native) | loginctl only |
| Systemd | **User service** (auto-start) | Manual startup |

This mirrors how Windows Dynamic Lock works internally:
- Establish baseline RSSI when device is nearby
- Lock when `avg_rssi - baseline < -10` (configurable)
- Delay lock by ~25s to avoid false triggers when briefly stepping away

## Requirements

```bash
sudo apt install bluez python3-dbus python3-gi
```

Your phone must be **Bluetooth paired** with the computer.

## Setup

**1. Find your phone's MAC address:**
```bash
bluetoothctl devices
```

**2. Install the script:**
```bash
cp bt_proximity_lock.py ~/.local/bin/
chmod +x ~/.local/bin/bt_proximity_lock.py
```

**3. Install systemd user service:**
```bash
cp bt-proximity-lock.service ~/.config/systemd/user/
# Edit the service file and set your phone's MAC:
sed -i 's/YOUR_PHONE_MAC_HERE/AA:BB:CC:DD:EE:FF/' ~/.config/systemd/user/bt-proximity-lock.service

systemctl --user daemon-reload
systemctl --user enable --now bt-proximity-lock.service
```

**4. Check it's working:**
```bash
journalctl --user -u bt-proximity-lock.service -f
```

## Configuration

Edit the `CONFIG` section at the top of `bt_proximity_lock.py`:

| Variable | Default | Description |
|---|---|---|
| `TARGET_MAC` | (from env) | Phone Bluetooth MAC address |
| `RSSI_DELTA` | `-10` | Signal drop threshold (dB) |
| `LOCK_DELAY` | `25` | Seconds before locking |
| `CHECK_INTERVAL` | `3` | Polling interval (seconds) |
| `RSSI_SAMPLES` | `5` | Sliding window for smoothing |
| `BASELINE_COUNT` | `8` | Startup samples for baseline |

## How it works

```
Startup: sample RSSI 8 times → establish baseline (e.g. +6 dBm)
Loop:
  Read RSSI → smooth with 5-sample sliding window
  delta = avg_rssi - baseline
  if delta < -10 for 25s → lock screen
  if device disappears (5 failures) for 25s → lock screen
```

## Tested on

- Zorin OS 18.1 (Ubuntu 24.04 Noble, GNOME 46)
- Phone: vivo X200 Pro (Android)

## License

MIT
