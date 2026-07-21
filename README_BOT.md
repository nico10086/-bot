# 🐱 猫娘 Bot

基于 DeepSeek + NapCatQQ 的 AI 聊天机器人，支持 QQ 私聊和群聊 @ 自动回复。

---

## 📥 给新用户的部署指南

### 前置要求

| 软件 | 版本要求 | 说明 |
|------|---------|------|
| Windows | 10 / 11 | 目前仅支持 Windows |
| QQNT | 9.9.x | 在 [im.qq.com](https://im.qq.com) 下载 |
| Python | 3.10+ | 推荐 3.11 |
| NapCat | Shell 版 | 从 [NapCat QQ 群](https://github.com/NapNeko/NapCatQQ) 获取 |
| DeepSeek API Key | - | 在 [platform.deepseek.com](https://platform.deepseek.com) 注册获取 |

### 安装步骤

```powershell
# 1. 克隆仓库
git clone https://github.com/nico10086/-bot.git
cd -bot

# 2. 创建 Python 虚拟环境并安装依赖
python -m venv env
env\Scripts\pip install -r requirements.txt

# 3. 配置环境变量
# 复制 .env.example 为 .env，填入你的 DeepSeek API Key
```

**.env 文件内容：**
```
DEEPSEEK_API_KEY=sk-你的密钥
BOT_NAME=猫娘           # 群聊中@不生效时的触发词，可选
```

### 获取 NapCat

NapCat 是 QQ 机器人框架，需要额外下载：

1. 加入 [NapCat 官方群](https://github.com/NapNeko/NapCatQQ) 获取最新 Shell 版
2. 解压到项目目录下的 `NapCat.Shell` 文件夹
3. 配置 `NapCat.Shell/config/onebot11.json`（WebSocket 端口改为 8080）

或者直接用项目已配好的版本（需自行安装对应 QQ 版本）。

### 启动

**方式一：双击 `start_bot.bat`**（推荐）
- 自动查找 QQ → 启动 NapCat → 弹出二维码 → 扫码登录 → Bot 上线

**方式二：手动分步启动**
```powershell
# 终端 1：启动 NapCat（管理员）
cd NapCat.Shell
.\start_napcat.bat

# 终端 2：启动 Bot
.\env\Scripts\python.exe qq_bot_standalone.py
```

### 常见问题

**Q：报"文件损坏，请重新安装QQ"？**
- 确认 QQNT 版本为 9.9.x
- 检查杀毒软件是否拦截了 NapCat 的 DLL 注入

**Q：二维码不弹窗？**
- `start_bot.bat` 会自动检测二维码文件并打开
- 也可以手动打开 `NapCat.Shell/cache/qrcode.png`

**Q：扫码后没反应？**
- 手机 QQ 上可能需要点"确认登录"
- 确认 WebSocket 端口 8080 没有被其他程序占用

---

## 🔧 运维指南（项目主人用）

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
