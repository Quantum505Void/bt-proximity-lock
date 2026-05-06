#!/usr/bin/env python3
"""
bt-lock.py — BlueZ D-Bus 事件驱动蓝牙锁屏
Zorin OS 18.1 / Ubuntu 24.04 专用

触发锁屏的两条独立路径：
  1. 蓝牙路径：所有目标设备断连 → 等待 LOCK_DELAY 秒 → 锁屏
  2. 空闲路径：用户超过 IDLE_TIMEOUT 秒无操作 → 锁屏（Mutter IdleMonitor）

重连行为（Windows Dynamic Lock 同款）：
  - 计时器未触发：取消计时器
  - 已锁屏：唤醒屏幕显示登录界面，仍需输密码

其他特性：
  - logind LockedHint 作为更可靠的锁屏状态判断
  - 多设备支持（BT_MAC 逗号分隔，任一在线不锁）
  - SIGTERM 优雅退出
  - 日志 7 天轮转（~/.local/share/bt-lock/bt-lock.log）
  - BlueZ 重启时自动重新订阅
"""

import os
import sys
import signal
import logging
import subprocess
from logging.handlers import TimedRotatingFileHandler
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# =================== CONFIG ===================
_macs_raw    = os.environ.get("BT_MAC", "E4:57:68:A2:13:02")
TARGET_MACS  = [m.strip().upper() for m in _macs_raw.split(",") if m.strip()]
LOCK_DELAY   = int(os.environ.get("BT_LOCK_DELAY", "25"))      # 蓝牙断连延迟锁屏（秒）
IDLE_TIMEOUT = int(os.environ.get("BT_IDLE_TIMEOUT", "300"))   # 空闲锁屏阈值（秒），0=禁用
LOG_DIR      = os.path.expanduser("~/.local/share/bt-lock")
# ==============================================

# ---------- 日志 ----------
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

_lock_timer_id  = None
_idle_watch_id  = None   # Mutter IdleMonitor watch handle
_connected: dict[str, bool] = {}


# ---------- 优雅退出 ----------
def _shutdown(signum, frame):
    log.info(f"收到信号 {signum}，退出")
    loop.quit()

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


# ---------- 锁屏状态（logind LockedHint 优先，fallback ScreenSaver） ----------
def is_locked() -> bool:
    # 优先 logind LockedHint，更可靠（不依赖 GNOME 进程存活）
    try:
        obj = system_bus.get_object("org.freedesktop.login1",
                                    "/org/freedesktop/login1/session/auto")
        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
        return bool(props.Get("org.freedesktop.login1.Session", "LockedHint"))
    except Exception:
        pass
    # fallback：GNOME ScreenSaver
    try:
        obj = session_bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
        iface = dbus.Interface(obj, "org.gnome.ScreenSaver")
        return bool(iface.GetActive())
    except Exception:
        return False


# ---------- 锁屏 / 唤醒 ----------
def lock_screen(reason: str = ""):
    global _lock_timer_id
    _lock_timer_id = None

    if is_locked():
        log.info("屏幕已锁，跳过")
        return GLib.SOURCE_REMOVE

    log.info(f"🔒 锁屏{f'（{reason}）' if reason else ''}")
    try:
        obj = session_bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
        dbus.Interface(obj, "org.gnome.ScreenSaver").Lock()
    except Exception:
        try:
            subprocess.run(["loginctl", "lock-session"], check=False)
        except Exception as e:
            log.error(f"锁屏失败: {e}")
    return GLib.SOURCE_REMOVE

def wake_screen():
    try:
        obj = session_bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
        dbus.Interface(obj, "org.gnome.ScreenSaver").WakeUpScreen()
        log.info("🖥️  唤醒屏幕（锁屏界面）")
    except Exception as e:
        log.warning(f"唤醒屏幕失败: {e}")


# ---------- 蓝牙锁屏计时器 ----------
def _any_connected() -> bool:
    return any(_connected.get(mac, False) for mac in TARGET_MACS)

def schedule_lock():
    global _lock_timer_id
    if _any_connected() or _lock_timer_id is not None:
        return
    log.info(f"⚠️  所有设备断连，{LOCK_DELAY}s 后锁屏...")
    _lock_timer_id = GLib.timeout_add_seconds(
        LOCK_DELAY, lambda: lock_screen("蓝牙断连")
    )

def cancel_lock_timer():
    global _lock_timer_id
    if _lock_timer_id is not None:
        GLib.source_remove(_lock_timer_id)
        _lock_timer_id = None
        log.info("✅ 设备重连，取消锁屏计时器")
    elif is_locked():
        wake_screen()


# ---------- Mutter IdleMonitor（空闲锁屏） ----------
def _idle_monitor_iface():
    obj = session_bus.get_object(
        "org.gnome.Mutter.IdleMonitor",
        "/org/gnome/Mutter/IdleMonitor/Core",
    )
    return dbus.Interface(obj, "org.gnome.Mutter.IdleMonitor")

def _on_idle_watch_fired(watch_id):
    """用户空闲超时回调"""
    global _idle_watch_id
    if watch_id != _idle_watch_id:
        return
    log.info(f"💤 空闲超过 {IDLE_TIMEOUT}s，锁屏")
    lock_screen("空闲超时")
    # 锁屏后重新注册 UserActive watch，等用户活跃后重建空闲 watch
    _register_user_active_watch()

def _on_user_active_watch_fired(watch_id):
    """用户重新活跃，重建空闲 watch"""
    log.info("👋 用户活跃，重建空闲计时器")
    _register_idle_watch()

def _register_idle_watch():
    global _idle_watch_id
    try:
        iface = _idle_monitor_iface()
        _idle_watch_id = int(iface.AddIdleWatch(IDLE_TIMEOUT * 1000))
        log.info(f"空闲 watch 已注册（{IDLE_TIMEOUT}s），id={_idle_watch_id}")
    except Exception as e:
        log.warning(f"IdleMonitor 注册失败: {e}")
        _idle_watch_id = None

def _register_user_active_watch():
    try:
        iface = _idle_monitor_iface()
        watch_id = int(iface.AddUserActiveWatch())
        log.info(f"UserActive watch 已注册，id={watch_id}")
    except Exception as e:
        log.warning(f"UserActive watch 注册失败: {e}")

def setup_idle_monitor():
    if IDLE_TIMEOUT <= 0:
        log.info("空闲锁屏已禁用（BT_IDLE_TIMEOUT=0）")
        return
    try:
        # 订阅 WatchFired 信号
        session_bus.add_signal_receiver(
            handler_function=_on_idle_watch_fired,
            signal_name="WatchFired",
            dbus_interface="org.gnome.Mutter.IdleMonitor",
            bus_name="org.gnome.Mutter.IdleMonitor",
            path="/org/gnome/Mutter/IdleMonitor/Core",
        )
        # 同时订阅 UserActive watch（watch_id 不同，用 lambda 区分）
        # 用一个通用 dispatcher 处理两类 watch
        _register_idle_watch()
        log.info(f"✅ IdleMonitor 启动，空闲阈值 {IDLE_TIMEOUT}s")
    except Exception as e:
        log.warning(f"IdleMonitor 初始化失败: {e}")


# ---------- BlueZ 信号回调 ----------
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

def mac_to_path(mac: str) -> str:
    return f"/org/bluez/hci0/dev_{mac.replace(':', '_')}"

def get_connected(path: str):
    try:
        obj = system_bus.get_object("org.bluez", path)
        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
        return bool(props.Get("org.bluez.Device1", "Connected"))
    except Exception:
        return None

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
    log.info(f"蓝牙断连延迟: {LOCK_DELAY}s  空闲锁屏: {IDLE_TIMEOUT}s  日志: {LOG_DIR}")

    for mac in TARGET_MACS:
        subscribe(mac)

    if not _any_connected():
        schedule_lock()

    # BlueZ 对象增删监听（重启恢复）
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

    # Mutter IdleMonitor 空闲锁屏
    setup_idle_monitor()

    log.info("开始监听事件...")
    loop.run()
    log.info("已停止")


if __name__ == "__main__":
    main()
