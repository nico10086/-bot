# 🐱 猫娘 Bot

基于 DeepSeek + NapCatQQ 的 AI 聊天机器人，支持 QQ 私聊和群聊 @ 自动回复。

> 📖 **快速上手请看 [`快速上手指南.txt`](快速上手指南.txt)**

---

## 快速部署

| 需求 | 说明 |
|------|------|
| Windows | 10 / 11 |
| QQNT | 9.9.x [下载](https://im.qq.com) |
| Python | 3.10+ 推荐 3.11 [下载](https://www.python.org/downloads) |
| DeepSeek API Key | [申请](https://platform.deepseek.com) |

```powershell
git clone https://github.com/nico10086/-bot.git
cd -bot
python -m venv env
env\Scripts\pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，填入你的 API Key。  
NapCat 已包含在项目中，**无需额外下载**。

双击 `start_app.bat` 启动桌面管理程序，点击「一键启动」即可。

---

## 主要功能

| 功能 | 说明 |
|------|------|
| 🤖 **AI 聊天** | QQ 群聊/私聊 @回复 |
| 🖥️ **桌面管理** | 一键启动/停止，系统托盘后台运行 |
| 🌐 **联网搜索** | Bing + DuckDuckGo 搜索，自动绕过反爬 |
| 📚 **知识库** | 丢 txt/Word/Excel 进 `knowledge_base/` 自动读取 |
| 🎭 **双性格** | 软萌猫娘 / 雌小鬼傲娇，UI 一键切换 |
| 💾 **模型管理** | 保存多组 API Key 和模型配置，快速切换 |
| 🔐 **权限系统** | `/setup master` 设置主人，`/memory` 添加核心记忆 |
| 🔒 **隐私保护** | 聊天记录/API Key/知识库均不上传 GitHub |

---

## 文件结构

```
qq_bot_standalone.py   ← Bot 核心
bot_app.py              ← 桌面管理程序
start_app.bat           ← 启动桌面版
mcp_web.py              ← 联网搜索
mcp_time.py             ← 时间工具
mcp_knowledge.py        ← 知识库引擎
knowledge_base/         ← 你的知识文件
NapCat.Shell/           ← QQ 机器人框架（已包含）
```

---

## 注意

- NapCat 的 DLL/EXE 已包含在仓库中，无需额外下载
- 需要自行安装 QQNT 并准备好 API Key
- 详细使用说明请看 [`快速上手指南.txt`](快速上手指南.txt)
