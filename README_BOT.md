# 🐱 猫娘 Bot 运维指南

## 启动

双击 `start_bot.bat` 即可一键启动（会自动以管理员权限跑 NapCat + QQ Bot）

启动后流程：
1. NapCat 注入 QQ → 弹出 QQ 登录窗口
2. 扫码登录小号
3. QQ Bot 自动连接 NapCat 的 WebSocket
4. 猫娘上线！🎉

## 保持在线

### 不要让电脑睡眠
```powershell
# 在 PowerShell 里执行，阻止睡眠（仅本会话有效）
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

### 关掉 VS Code 不会影响 Bot

Bot 是在**独立终端**里跑的，关掉 VS Code 也没关系。但别关掉那个终端窗口。

### 如果想后台运行（不弹窗）

可以用 `nssm` 把 `qq_bot_standalone.py` 注册为 Windows 服务，这样开机自启、后台静默运行。

```powershell
# 下载 nssm: https://nssm.cc/download
nssm install 猫娘Bot "C:\Users\nico\Desktop\ai-agent\env\Scripts\python.exe" "C:\Users\nico\Desktop\ai-agent\qq_bot_standalone.py"
nssm start 猫娘Bot
```

### 如果 Bot 崩了

`start_bot.bat` 里已经加了自动重启逻辑，Bot 挂了会自动重连。NapCat 如果崩了需要手动重新运行 `start_napcat.bat`。

## 重启流程

如果出问题了，按顺序来：
1. 关掉所有终端
2. 双击 `start_bot.bat`
3. QQ 弹窗出来后扫码登录
4. 等看到 `[WS] 已连接！等待 QQ 消息...` 就搞定

## 总结

| 需求 | 做法 |
|------|------|
| 开机自启 | 把 `start_bot.bat` 扔进 `shell:startup` |
| 防睡眠 | `powercfg /change standby-timeout-ac 0` |
| Bot 挂了 | `start_bot.bat` 会自动重启 |
| QQ 掉了 | 重新扫码登录即可 |
