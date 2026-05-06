#!/usr/bin/env python3
"""
bt-lock.py — BlueZ D-Bus 事件驱动蓝牙锁屏
Zorin OS 18.1 / Ubuntu 24.04 专用

逻辑：
  - 监听 org.bluez.Device1.Connected 属性变化（事件驱动，零轮询）
  - 所有目标设备断连 → 等待 LOCK_DELAY 秒 → 锁屏
  - 任一设备重连 → 取消计时器 / 唤醒屏幕（Windows Dynamic Lock 同款）
  - SIGTERM 优雅退出，日志 7 天轮转
"""

import os
import sys
import signal
import logging
from logging.handlers import TimedRotatingFileHandler
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# =================== CONFIG ===================
# 多设备：逗号分隔，任一在线就不锁
_macs_raw  = os.environ.get("BT_MAC", "E4:57:68:A2:13:02")
TARGET_MACS = [m.strip().upper() for m in _macs_raw.split(",") if m.strip()]
LOCK_DELAY  = int(os.environ.get("BT_LOCK_DELAY", "25"))
LOG_DIR     = os.path.expanduser("~/.local/share/bt-lock")
# ==============================================

# ---------- 日志：stdout + 7 天轮转文件 ----------
os.makedirs(LOG_DIR, exist_ok=True)
_fmt = logging.Formatter("%(asctime)s [bt-lock] %(message)s", datefmt="%H:%M:%S")

_file_h = TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "bt-lock.log"),
    when="midnight", interval=1, backupCount=7, encoding="utf-8",
)
_file_h.setFormatter(_fmt)

_stream_h = logging.StreamHandler(sys.stdout)
_stream_h.setFormatter(_fmt)

log = logging.getLogger("bt-lock")
log.setLevel(logging.INFO)
log.addHandler(_file_h)
log.addHandler(_stream_h)

# ---------- D-Bus & GLib ----------
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
system_bus  = dbus.SystemBus()
session_bus = dbus.SessionBus()
loop        = GLib.MainLoop()

_lock_timer_id = None
# 每个 MAC 的连接状态缓存
_connected: dict[str, bool] = {}


# ---------- 优雅退出 ----------
def _shutdown(signum, frame):
    log.info(f"收到信号 {signum}，退出")
    loop.quit()

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


# ---------- GNOME ScreenSaver ----------
def _screensaver():
    obj = session_bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
    return dbus.Interface(obj, "org.gnome.ScreenSaver")

def is_locked() -> bool:
    try:
        return bool(_screensaver().GetActive())
    except Exception:
        return False

def lock_screen():
    global _lock_timer_id
    _lock_timer_id = None
    if is_locked():
        log.info("屏幕已锁，跳过")
        return GLib.SOURCE_REMOVE
    try:
        _screensaver().Lock()
        log.info("🔒 锁屏（GNOME ScreenSaver）")
    except Exception:
        try:
            import subprocess
            subprocess.run(["loginctl", "lock-session"], check=False)
            log.info("🔒 锁屏（loginctl）")
        except Exception as e:
            log.error(f"锁屏失败: {e}")
    return GLib.SOURCE_REMOVE

def wake_screen():
    try:
        _screensaver().WakeUpScreen()
        log.info("🖥️  唤醒屏幕（锁屏界面）")
    except Exception as e:
        log.warning(f"唤醒屏幕失败: {e}")


# ---------- 计时器 ----------
def _any_connected() -> bool:
    return any(_connected.get(mac, False) for mac in TARGET_MACS)

def schedule_lock():
    global _lock_timer_id
    if _any_connected():
        return  # 还有设备在线，不锁
    if _lock_timer_id is not None:
        return  # 计时器已在跑
    log.info(f"⚠️  所有设备断连，{LOCK_DELAY}s 后锁屏...")
    _lock_timer_id = GLib.timeout_add_seconds(LOCK_DELAY, lock_screen)

def cancel_lock_timer():
    global _lock_timer_id
    if _lock_timer_id is not None:
        GLib.source_remove(_lock_timer_id)
        _lock_timer_id = None
        log.info("✅ 设备重连，取消锁屏计时器")
    elif is_locked():
        wake_screen()


# ---------- BlueZ 工具 ----------
def mac_to_path(mac: str) -> str:
    return f"/org/bluez/hci0/dev_{mac.replace(':', '_')}"

def get_connected(path: str):
    try:
        obj = system_bus.get_object("org.bluez", path)
        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
        return bool(props.Get("org.bluez.Device1", "Connected"))
    except Exception:
        return None


# ---------- 信号回调 ----------
def on_properties_changed(iface, changed, invalidated, mac=None):
    if iface != "org.bluez.Device1" or "Connected" not in changed:
        return
    connected = bool(changed["Connected"])
    _connected[mac] = connected
    log.info(f"{'🟢 连接' if connected else '🔴 断连'} {mac}")
    if connected:
        cancel_lock_timer()
    else:
        schedule_lock()

def subscribe(mac: str):
    path = mac_to_path(mac)
    system_bus.add_signal_receiver(
        handler_function=lambda iface, changed, inv, m=mac: on_properties_changed(iface, changed, inv, mac=m),
        signal_name="PropertiesChanged",
        dbus_interface="org.freedesktop.DBus.Properties",
        bus_name="org.bluez",
        path=path,
    )
    st = get_connected(path)
    _connected[mac] = bool(st)
    log.info(f"已订阅 {mac}  当前={'连接' if st else '断连' if st is False else '未知'}")

def on_interfaces_added(path, interfaces):
    if "org.bluez.Device1" not in interfaces:
        return
    addr = str(interfaces["org.bluez.Device1"].get("Address", "")).upper()
    if addr in TARGET_MACS:
        log.info(f"设备重新出现: {addr}，重新订阅")
        subscribe(addr)

def on_interfaces_removed(path, interfaces):
    if "org.bluez.Device1" not in interfaces:
        return
    for mac in TARGET_MACS:
        if path == mac_to_path(mac):
            log.info(f"设备消失: {mac}")
            _connected[mac] = False
            schedule_lock()


# ---------- 主程序 ----------
def main():
    if not TARGET_MACS:
        log.error("未设置 BT_MAC")
        sys.exit(1)

    log.info(f"启动 — 目标设备: {TARGET_MACS}")
    log.info(f"断连延迟: {LOCK_DELAY}s  日志: {LOG_DIR}")

    for mac in TARGET_MACS:
        subscribe(mac)

    # 初始状态：所有设备都不在线 → 启动计时
    if not _any_connected():
        schedule_lock()

    system_bus.add_signal_receiver(
        on_interfaces_added,
        signal_name="InterfacesAdded",
        dbus_interface="org.freedesktop.DBus.ObjectManager",
        bus_name="org.bluez", path="/",
    )
    system_bus.add_signal_receiver(
        on_interfaces_removed,
        signal_name="InterfacesRemoved",
        dbus_interface="org.freedesktop.DBus.ObjectManager",
        bus_name="org.bluez", path="/",
    )

    log.info("开始监听事件...")
    loop.run()
    log.info("已停止")


if __name__ == "__main__":
    main()
