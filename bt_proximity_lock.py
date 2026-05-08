#!/usr/bin/env python3
"""
bt-proximity-lock — Linux Dynamic Lock via Bluetooth RSSI Delta
Inspired by Windows Hello Dynamic Lock

Author: Quantum404Void
License: MIT
"""

import subprocess
import time
import logging
import sys
import os
import dbus
from collections import deque

# ===================== CONFIG =====================
TARGET_MAC     = os.environ.get("BT_MAC", "")   # Phone Bluetooth MAC
RSSI_DELTA     = -10     # Lock when signal drops by this much (Windows default: -10)
LOCK_DELAY     = 25      # Seconds signal must stay low before locking (~Windows 30s)
CHECK_INTERVAL = 3       # Polling interval in seconds
RSSI_SAMPLES   = 5       # Sliding window size for RSSI smoothing
BASELINE_COUNT = 8       # Samples to build baseline RSSI at startup
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bt-lock] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger()


def get_rssi(mac: str):
    """Read RSSI of a paired Bluetooth device. Returns None on failure."""
    try:
        result = subprocess.run(
            ["hcitool", "rssi", mac],
            capture_output=True, text=True, timeout=4
        )
        if "RSSI return value:" in result.stdout:
            return int(result.stdout.split(":")[-1].strip())
    except Exception:
        pass
    return None


def lock_screen():
    """Lock screen via dbus (GNOME/Wayland), fallback to loginctl."""
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
        iface = dbus.Interface(obj, "org.gnome.ScreenSaver")
        iface.Lock()
        log.info("🔒 Locked (dbus)")
        return
    except Exception:
        pass
    subprocess.run(["loginctl", "lock-session"], check=False)
    log.info("🔒 Locked (loginctl)")


def build_baseline() -> float:
    """Sample RSSI at startup to establish baseline (device nearby)."""
    log.info(f"Building baseline RSSI ({BASELINE_COUNT} samples)...")
    samples = []
    for i in range(BASELINE_COUNT):
        rssi = get_rssi(TARGET_MAC)
        if rssi is not None:
            samples.append(rssi)
            log.info(f"  Sample {i+1}/{BASELINE_COUNT}: RSSI={rssi:+d}")
        else:
            log.warning(f"  Sample {i+1}/{BASELINE_COUNT}: failed (device not connected?)")
        time.sleep(CHECK_INTERVAL)

    if not samples:
        log.warning("Could not establish baseline, defaulting to 0")
        return 0.0

    baseline = sum(samples) / len(samples)
    log.info(f"Baseline RSSI = {baseline:+.1f} (avg of {len(samples)} samples)")
    return baseline


def main():
    if not TARGET_MAC:
        log.error("BT_MAC not set. Usage: BT_MAC=AA:BB:CC:DD:EE:FF python3 bt_proximity_lock.py")
        sys.exit(1)

    log.info(f"Starting, monitoring: {TARGET_MAC}")
    log.info(f"Delta threshold: {RSSI_DELTA}, lock delay: {LOCK_DELAY}s")

    baseline = build_baseline()

    recent     = deque(maxlen=RSSI_SAMPLES)
    away_since = None
    locked     = False
    miss_count = 0

    log.info("Monitoring started...")

    while True:
        rssi = get_rssi(TARGET_MAC)

        if rssi is not None:
            miss_count = 0
            recent.append(rssi)
            avg = sum(recent) / len(recent)
            delta = avg - baseline
            log.info(f"RSSI={rssi:+d}  avg={avg:+.1f}  baseline={baseline:+.1f}  delta={delta:+.1f}")

            if delta < RSSI_DELTA:
                if away_since is None:
                    away_since = time.time()
                    log.info(f"⚠️  Signal dropped {delta:+.1f}, starting countdown...")
                elapsed = time.time() - away_since
                log.info(f"   Away for {elapsed:.0f}s / {LOCK_DELAY}s")
                if not locked and elapsed >= LOCK_DELAY:
                    lock_screen()
                    locked = True
            else:
                if away_since is not None:
                    log.info("✅ Signal restored")
                away_since = None
                if locked:
                    log.info("(Screen locked, manual unlock required)")
        else:
            miss_count += 1
            log.info(f"⚠️  RSSI read failed ({miss_count} consecutive)")
            if miss_count >= 5:
                if away_since is None:
                    away_since = time.time()
                elapsed = time.time() - away_since
                if not locked and elapsed >= LOCK_DELAY:
                    log.info("Device completely out of range, locking")
                    lock_screen()
                    locked = True

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
