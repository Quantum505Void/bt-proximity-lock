# bt-proximity-lock

**蓝牙近距离自动锁屏** — Zorin OS 18.1 / Ubuntu 24.04 专用

手机离开 → 自动锁屏；手机回来 → 唤醒登录界面（仍需认证，与 Windows Dynamic Lock 行为一致）。

---

## 特性

| 特性 | 说明 |
|------|------|
| 🔵 D-Bus 事件驱动 | 监听 `org.bluez.Device1.Connected`，零 CPU 轮询 |
| 💤 空闲锁屏 | 集成 `org.gnome.Mutter.IdleMonitor`，超时无操作自动锁 |
| 🔒 可靠锁屏状态 | `logind LockedHint` 优先，fallback GNOME ScreenSaver |
| 🖥️ Windows 同款唤醒 | 设备回来仅唤醒屏幕，不跳过认证 |
| 📱 多设备支持 | `BT_MAC` 逗号分隔，任一在线不锁 |
| ♻️ 自动重连 | BlueZ 重启后自动重新订阅 |
| 📋 日志轮转 | 7 天自动清理，`~/.local/share/bt-lock/bt-lock.log` |
| 🛑 优雅退出 | SIGTERM 干净停止，systemd stop 无残留 |

---

## 安装

```bash
curl -fsSL https://raw.githubusercontent.com/Quantum505Void/bt-proximity-lock/main/install.sh | bash
```

或手动：

```bash
# 1. 找到手机 MAC 地址
bluetoothctl devices

# 2. 复制脚本和服务文件
cp bt-lock.py ~/.local/bin/bt-lock.py
chmod +x ~/.local/bin/bt-lock.py
cp bt-lock.service ~/.config/systemd/user/bt-lock.service

# 3. 修改 MAC 地址
sed -i 's/E4:57:68:A2:13:02/你的MAC/' ~/.config/systemd/user/bt-lock.service

# 4. 启用服务
systemctl --user daemon-reload
systemctl --user enable --now bt-lock.service
```

---

## 配置

通过 systemd 服务的 `Environment` 字段配置：

```ini
# ~/.config/systemd/user/bt-lock.service
[Service]
Environment=BT_MAC=E4:57:68:A2:13:02         # 手机 MAC（逗号分隔多设备）
Environment=BT_LOCK_DELAY=25                  # 蓝牙断连后延迟锁屏（秒）
Environment=BT_IDLE_TIMEOUT=300               # 空闲锁屏阈值（秒），0=禁用
```

修改后执行：
```bash
systemctl --user daemon-reload
systemctl --user restart bt-lock.service
```

---

## 工作原理

```
触发路径 1 — 蓝牙：
  设备断连 ──→ 等待 BT_LOCK_DELAY 秒 ──→ 锁屏
  设备重连 ──→ 取消计时器 / 唤醒屏幕

触发路径 2 — 空闲：
  无操作超过 BT_IDLE_TIMEOUT 秒 ──→ 锁屏
  用户活跃 ──→ 重置空闲计时器
```

两条路径独立触发，互不干扰。

---

## 查看日志

```bash
# 实时日志
journalctl --user -u bt-lock.service -f

# 历史日志文件
tail -f ~/.local/share/bt-lock/bt-lock.log
```

---

## 技术栈

- **BlueZ D-Bus** `org.bluez.Device1.Connected` — 连接状态事件
- **Mutter IdleMonitor** `org.gnome.Mutter.IdleMonitor` — 用户空闲检测
- **logind LockedHint** `org.freedesktop.login1.Session` — 可靠锁屏状态
- **GNOME ScreenSaver** `org.gnome.ScreenSaver` — 锁屏 / 唤醒操作
- **GLib MainLoop** — 事件循环，替代轮询

---

## 卸载

```bash
bash uninstall.sh
```

---

## License

MIT
