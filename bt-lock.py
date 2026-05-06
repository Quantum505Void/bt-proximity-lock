#!/usr/bin/env python3
"""
bt-lock.py — BlueZ D-Bus 事件驱动蓝牙锁屏
Zorin OS 18.1 / Ubuntu 24.04 专用

逻辑：
  - 监听 org.bluez.Device1.Connected 属性变化（事件驱动，零轮询）
  - 断连 → 等待 LOCK_DELAY 秒 → 锁屏
  - 重连 → 取消计时器，不解锁（与 Windows Dynamic Lock 一致）
  - 已锁屏 / 已有锁屏计时器时不重复触发
  - BlueZ 重启时自动重新订阅信号
"""

import os
import sys
import logging
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# =================== CONFIG ===================
TARGET_MAC    = os.environ.get("BT_MAC", "E4:57:68:A2:13:02")
LOCK_DELAY    = int(os.environ.get("BT_LOCK_DELAY", "25"))   # 断连后延迟锁屏秒数
# ==============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bt-lock] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger()

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

system_bus  = dbus.SystemBus()
session_bus = dbus.SessionBus()
loop        = GLib.MainLoop()

_lock_timer_id = None   # GLib 定时器 handle


# ---------- 锁屏 ----------

def is_already_locked() -> bool:
    """查询 GNOME ScreenSaver 是否已激活，避免重复锁"""
    try:
        obj = session_bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
        iface = dbus.Interface(obj, "org.gnome.ScreenSaver")
        return bool(iface.GetActive())
    except Exception:
        return False


def lock_screen():
    global _lock_timer_id
    _lock_timer_id = None

    if is_already_locked():
        log.info("屏幕已锁，跳过")
        return GLib.SOURCE_REMOVE

    # 优先 GNOME ScreenSaver，fallback loginctl
    try:
        obj = session_bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
        iface = dbus.Interface(obj, "org.gnome.ScreenSaver")
        iface.Lock()
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
    """唤醒屏幕显示登录界面，不跳过认证（Windows Dynamic Lock 同款）"""
    try:
        obj = session_bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver")
        iface = dbus.Interface(obj, "org.gnome.ScreenSaver")
        iface.WakeUpScreen()
        log.info("🖥️  唤醒屏幕（锁屏界面）")
    except Exception as e:
        log.warning(f"唤醒屏幕失败: {e}")


def cancel_lock_timer():
    global _lock_timer_id
    if _lock_timer_id is not None:
        GLib.source_remove(_lock_timer_id)
        _lock_timer_id = None
        log.info("✅ 设备重连，取消锁屏计时器")
    elif is_already_locked():
        # 已锁屏时设备回来：唤醒屏幕提示登录
        wake_screen()


def schedule_lock():
    global _lock_timer_id
    if _lock_timer_id is not None:
        log.info(f"⚠️  断连（计时器已在运行）")
        return
    log.info(f"⚠️  断连，{LOCK_DELAY}s 后锁屏...")
    _lock_timer_id = GLib.timeout_add_seconds(LOCK_DELAY, lock_screen)


# ---------- 设备路径 ----------

def mac_to_dbus_path(mac: str) -> str:
    return f"/org/bluez/hci0/dev_{mac.replace(':', '_')}"


def get_device_connected(path: str) -> bool | None:
    """获取当前连接状态，失败返回 None"""
    try:
        obj = system_bus.get_object("org.bluez", path)
        props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
        return bool(props.Get("org.bluez.Device1", "Connected"))
    except Exception:
        return None


# ---------- 信号处理 ----------

def on_properties_changed(interface, changed, invalidated, path=None):
    if interface != "org.bluez.Device1":
        return
    if "Connected" not in changed:
        return

    connected = bool(changed["Connected"])
    log.info(f"{'🟢 连接' if connected else '🔴 断连'} ({path})")

    if connected:
        cancel_lock_timer()
    else:
        schedule_lock()


def subscribe_device(path: str):
    """订阅设备的 PropertiesChanged 信号"""
    try:
        system_bus.add_signal_receiver(
            handler_function=lambda iface, changed, inv, p=path: on_properties_changed(iface, changed, inv, path=p),
            signal_name="PropertiesChanged",
            dbus_interface="org.freedesktop.DBus.Properties",
            bus_name="org.bluez",
            path=path,
        )
        log.info(f"已订阅: {path}")

        # 检查当前连接状态
        connected = get_device_connected(path)
        if connected is False:
            log.info("设备当前未连接，启动时触发计时器")
            schedule_lock()
        elif connected is True:
            log.info("设备当前已连接")
        else:
            log.warning("无法读取设备状态（设备可能不在 BlueZ 对象列表中）")
    except Exception as e:
        log.error(f"订阅失败: {e}")


def on_interfaces_added(path, interfaces):
    """BlueZ 重启 / 设备首次出现时重新订阅"""
    if "org.bluez.Device1" in interfaces:
        dev = interfaces["org.bluez.Device1"]
        if str(dev.get("Address", "")).upper() == TARGET_MAC.upper():
            log.info(f"设备重新出现: {path}，重新订阅")
            subscribe_device(path)


def on_interfaces_removed(path, interfaces):
    if "org.bluez.Device1" in interfaces:
        # 设备消失（BlueZ 重启等），调度锁屏
        target_path = mac_to_dbus_path(TARGET_MAC)
        if path == target_path:
            log.info("设备从 BlueZ 消失")
            schedule_lock()


# ---------- 主程序 ----------

def main():
    if not TARGET_MAC:
        log.error("未设置 BT_MAC")
        sys.exit(1)

    target_path = mac_to_dbus_path(TARGET_MAC)
    log.info(f"启动 — 目标设备: {TARGET_MAC}")
    log.info(f"D-Bus 路径: {target_path}")
    log.info(f"断连延迟: {LOCK_DELAY}s")

    # 订阅目标设备信号
    subscribe_device(target_path)

    # 监听 BlueZ 对象增删（重启恢复）
    system_bus.add_signal_receiver(
        on_interfaces_added,
        signal_name="InterfacesAdded",
        dbus_interface="org.freedesktop.DBus.ObjectManager",
        bus_name="org.bluez",
        path="/",
    )
    system_bus.add_signal_receiver(
        on_interfaces_removed,
        signal_name="InterfacesRemoved",
        dbus_interface="org.freedesktop.DBus.ObjectManager",
        bus_name="org.bluez",
        path="/",
    )

    log.info("开始监听事件...")
    try:
        loop.run()
    except KeyboardInterrupt:
        log.info("退出")


if __name__ == "__main__":
    main()
