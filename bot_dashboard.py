"""
🐱 猫娘 Bot 管理面板 - Web 可视化后台
一键启动 / 停止 / 重启，查看日志，快速配置
用法：双击运行或在终端执行 python bot_dashboard.py
"""
import os
import sys
import json
import subprocess
import threading
import time
import signal
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ── 配置 ──
HOST = "127.0.0.1"
PORT = 5000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
BOT_SCRIPT = os.path.join(BASE_DIR, "qq_bot_standalone.py")

# ── 路径常量 ──
NAPCAT_DIR = os.path.join(BASE_DIR, "NapCat.Shell")
NAPCAT_LAUNCHER = os.path.join(NAPCAT_DIR, "NapCatWinBootMain.exe")
NAPCAT_INJECT = os.path.join(NAPCAT_DIR, "NapCatWinBootHook.dll")
NAPCAT_MAIN = os.path.join(NAPCAT_DIR, "napcat.mjs")
NAPCAT_PATCH = os.path.join(NAPCAT_DIR, "qqnt.json")
NAPCAT_LOAD_JS = os.path.join(NAPCAT_DIR, "loadNapCat.js")
QR_PATH = os.path.join(NAPCAT_DIR, "cache", "qrcode.png")

# ── 进程管理 ──
_bot_process: subprocess.Popen | None = None
_napcat_process: subprocess.Popen | None = None
_bot_logs: list[str] = []
_log_lock = threading.Lock()
_env_config: dict[str, str] = {}
_startup_stage: str = "idle"  # idle → napcat → qr → websocket → bot_running
_ws_ready: bool = False


def load_env() -> dict[str, str]:
    """读取 .env 配置"""
    config = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    config[key.strip()] = val.strip()
    return config


def save_env(config: dict[str, str]) -> None:
    """保存配置到 .env"""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    # 更新现有 key，追加新 key
    written_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in config:
                new_lines.append(f"{key}={config[key]}\n")
                written_keys.add(key)
                continue
        new_lines.append(line)
    for key, val in config.items():
        if key not in written_keys:
            new_lines.append(f"{key}={val}\n")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def add_log(msg: str) -> None:
    """添加日志（线程安全）"""
    timestamp = time.strftime("%H:%M:%S")
    with _log_lock:
        _bot_logs.append(f"[{timestamp}] {msg}")
        if len(_bot_logs) > 500:  # 最多保留 500 行
            _bot_logs[:100] = []


def get_bot_status() -> dict:
    """获取 Bot + NapCat 综合运行状态"""
    global _bot_process, _napcat_process, _startup_stage, _ws_ready
    # 检查 NapCat 进程
    napcat_running = False
    if _napcat_process is not None:
        ret = _napcat_process.poll()
        if ret is not None:
            _napcat_process = None
        else:
            napcat_running = True
    # 检查 Bot 进程
    bot_running = False
    if _bot_process is not None:
        ret = _bot_process.poll()
        if ret is not None:
            _bot_process = None
        else:
            bot_running = True
    # 二维码是否存在
    qr_exists = os.path.exists(QR_PATH)
    return {
        "bot_running": bot_running,
        "napcat_running": napcat_running,
        "stage": _startup_stage,
        "ws_ready": _ws_ready,
        "qr_exists": qr_exists,
        "pid": _bot_process.pid if _bot_process else None,
    }


def find_qq_path() -> str | None:
    """从注册表查找 QQ 安装路径"""
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE,):
        for subkey in (
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
        ):
            try:
                key = winreg.OpenKey(hive, subkey)
                val, _ = winreg.QueryValueEx(key, "UninstallString")
                winreg.CloseKey(key)
                qq_path = os.path.join(os.path.dirname(val), "QQ.exe")
                if os.path.exists(qq_path):
                    return qq_path
            except Exception:
                continue
    return None


def start_napcat() -> str:
    """启动 NapCat（查找 QQ → 注入 → 生成二维码）"""
    global _napcat_process, _startup_stage, _ws_ready

    if _napcat_process is not None and _napcat_process.poll() is None:
        return "NapCat 已经在运行了"

    qq_path = find_qq_path()
    if not qq_path:
        add_log("❌ 找不到 QQ.exe，请确认已安装 QQNT")
        return "❌ 找不到 QQ.exe，请确认已安装 QQNT"

    add_log(f"🔍 找到 QQ: {qq_path}")
    add_log("🚀 正在启动 NapCat 注入 QQ...")

    # 生成 loadNapCat.js
    main_path = NAPCAT_MAIN.replace("\\", "/")
    with open(NAPCAT_LOAD_JS, "w", encoding="utf-8") as f:
        f.write(f'(async () => {{await import("file:///{main_path}")}})()\n')

    # 清理旧二维码
    if os.path.exists(QR_PATH):
        os.remove(QR_PATH)

    # 设置环境变量
    env = os.environ.copy()
    env["NAPCAT_PATCH_PACKAGE"] = NAPCAT_PATCH
    env["NAPCAT_LOAD_PATH"] = NAPCAT_LOAD_JS
    env["NAPCAT_INJECT_PATH"] = NAPCAT_INJECT
    env["NAPCAT_LAUNCHER_PATH"] = NAPCAT_LAUNCHER

    try:
        _napcat_process = subprocess.Popen(
            [NAPCAT_LAUNCHER, qq_path, NAPCAT_INJECT],
            cwd=NAPCAT_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        _startup_stage = "napcat"
        _ws_ready = False
        add_log("✅ NapCat 已启动，等待二维码生成...")

        # 后台线程：监控二维码 + WebSocket 端口
        def monitor_startup():
            global _startup_stage, _ws_ready
            qr_opened = False
            for i in range(120):  # 最多等 120 秒
                time.sleep(1)
                # 检测二维码
                if not qr_opened and os.path.exists(QR_PATH):
                    qr_opened = True
                    _startup_stage = "qr"
                    add_log(f"📱 二维码已生成（等待 {i+1} 秒）")
                # 检测 WebSocket 端口
                if not _ws_ready:
                    try:
                        result = subprocess.run(
                            ["netstat", "-an"],
                            capture_output=True, text=True, timeout=5,
                        )
                        if ":8080" in result.stdout and "LISTENING" in result.stdout:
                            _ws_ready = True
                            _startup_stage = "websocket"
                            add_log(f"✅ WebSocket 端口 8080 已就绪（耗时 {i+1} 秒）")
                    except Exception:
                        pass
                if qr_opened and _ws_ready:
                    _startup_stage = "ready"
                    add_log("🎉 NapCat 就绪，可以启动 Bot 了！")
                    break
            if not _ws_ready:
                add_log("⚠️ 等待超时，NapCat 可能未完全启动")

        t = threading.Thread(target=monitor_startup, daemon=True)
        t.start()
        return f"✅ NapCat 已启动，二维码即将生成"
    except Exception as e:
        add_log(f"❌ NapCat 启动失败：{e}")
        return f"❌ NapCat 启动失败：{e}"


def stop_napcat() -> str:
    """停止 NapCat 和 QQ"""
    global _napcat_process, _startup_stage, _ws_ready
    try:
        subprocess.run(["taskkill", "/F", "/IM", "NapCatWinBootMain.exe"],
                       capture_output=True, timeout=5)
        subprocess.run(["taskkill", "/F", "/IM", "QQ.exe"],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    _napcat_process = None
    _startup_stage = "idle"
    _ws_ready = False
    add_log("⏹ NapCat 已停止")
    return "✅ NapCat 已停止"


def start_bot() -> str:
    """启动 Bot（前提：NapCat 已在运行）"""
    global _bot_process
    if _bot_process is not None and _bot_process.poll() is None:
        return "Bot 已经在运行中了喵~"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        _bot_process = subprocess.Popen(
            [sys.executable, BOT_SCRIPT],
            cwd=BASE_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        add_log("🚀 Bot 已启动")

        def read_output():
            global _bot_process
            try:
                for line in iter(_bot_process.stdout.readline, ""):
                    if line:
                        add_log(line.rstrip("\n\r"))
            except Exception:
                pass
            finally:
                add_log("⏹ Bot 进程已退出")

        t = threading.Thread(target=read_output, daemon=True)
        t.start()
        return "✅ Bot 启动成功！"
    except Exception as e:
        add_log(f"❌ Bot 启动失败：{e}")
        return f"❌ Bot 启动失败：{e}"


def start_full() -> str:
    """一键全流程启动：NapCat → 等就绪 → Bot"""
    status = get_bot_status()
    if status["bot_running"]:
        return "猫娘已经在运行了喵~"

    # 先启动 NapCat
    msg = start_napcat()
    if "失败" in msg:
        return msg

    # 等 WebSocket 就绪后自动启动 Bot
    def auto_start_bot():
        global _startup_stage
        for _ in range(150):  # 最多等 150 秒
            time.sleep(1)
            if _ws_ready:
                time.sleep(2)  # 再等 2 秒让 NapCat 稳定
                result = start_bot()
                add_log(result)
                _startup_stage = "bot_running"
                return
        add_log("⏱ NapCat 启动超时，请扫码后手动点击「启动 Bot」")

    t = threading.Thread(target=auto_start_bot, daemon=True)
    t.start()
    return "🚀 全流程启动中（NapCat → 二维码 → Bot）..."


def stop_bot() -> str:
    """停止 Bot"""
    global _bot_process
    status = get_bot_status()
    if status["bot_running"]:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(status["pid"])],
                           capture_output=True, timeout=5)
        except Exception:
            pass
        _bot_process = None
        add_log("⏹ Bot 已停止")
    return "✅ Bot 已停止"


def stop_full() -> str:
    """完全停止：Bot + NapCat + QQ"""
    msg1 = stop_bot()
    time.sleep(0.5)
    msg2 = stop_napcat()
    return f"{msg1}\n{msg2}"


def restart_full() -> str:
    """完全重启"""
    stop_full()
    time.sleep(2)
    return start_full()


# ── HTTP 服务器 ──

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/status":
            self._json_response(get_bot_status())
        elif path == "/api/logs":
            with _log_lock:
                logs = list(_bot_logs)
            self._json_response({"logs": logs})
        elif path == "/api/config":
            self._json_response(load_env())
        elif path == "/api/qrcode":
            self._serve_qrcode()
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len else "{}"
        data = json.loads(body) if body else {}

        if path == "/api/start":
            msg = start_full()
            self._json_response({"message": msg, "status": get_bot_status()})
        elif path == "/api/stop":
            msg = stop_full()
            self._json_response({"message": msg, "status": get_bot_status()})
        elif path == "/api/restart":
            msg = restart_full()
            self._json_response({"message": msg, "status": get_bot_status()})
        elif path == "/api/start-bot":
            msg = start_bot()
            self._json_response({"message": msg, "status": get_bot_status()})
        elif path == "/api/start-napcat":
            msg = start_napcat()
            self._json_response({"message": msg, "status": get_bot_status()})
        elif path == "/api/config":
            if "config" in data:
                save_env(data["config"])
                add_log("⚙️ 配置已更新")
                self._json_response({"message": "配置已保存 ✅", "config": load_env()})
            else:
                self._json_response({"error": "缺少 config 字段"}, 400)
        else:
            self._json_response({"error": "Not found"}, 404)

    def _serve_qrcode(self):
        """提供二维码图片"""
        if os.path.exists(QR_PATH):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with open(QR_PATH, "rb") as f:
                self.wfile.write(f.read())
        else:
            self._json_response({"error": "二维码还未生成"}, 404)

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # 关掉默认日志


# ── HTML 页面（内嵌） ──

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🐱 猫娘 Bot 管理面板</title>
<style>
  :root {
    --bg: #1a1b2e;
    --card: #232545;
    --card-hover: #2a2d50;
    --primary: #f472b6;
    --primary-dim: #be3f7a;
    --accent: #a78bfa;
    --green: #34d399;
    --red: #f87171;
    --yellow: #fbbf24;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --border: #334155;
    --radius: 12px;
    --shadow: 0 4px 24px rgba(0,0,0,.3);
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: var(--bg); color: var(--text); min-height: 100vh;
  }
  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }

  /* Header */
  header {
    text-align: center; padding: 32px 0 24px;
    border-bottom: 1px solid var(--border); margin-bottom: 24px;
  }
  header h1 { font-size: 28px; }
  header h1 span { color: var(--primary); }
  header p { color: var(--text-dim); margin-top: 6px; font-size: 14px; }

  /* Status Bar */
  .status-bar {
    background: var(--card); border-radius: var(--radius); padding: 20px 24px;
    box-shadow: var(--shadow); margin-bottom: 20px;
  }
  .status-row {
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 12px;
  }
  .status-item { display: flex; align-items: center; gap: 10px; }
  .status-dot {
    width: 12px; height: 12px; border-radius: 50%;
    background: var(--red); transition: all .3s;
    box-shadow: 0 0 6px var(--red);
  }
  .status-dot.on { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .status-label { font-size: 13px; color: var(--text-dim); }
  .status-value { font-size: 14px; font-weight: 600; }

  .status-details {
    display: flex; gap: 24px; flex-wrap: wrap;
    margin-top: 12px; padding-top: 12px;
    border-top: 1px solid var(--border);
    font-size: 13px; color: var(--text-dim);
  }

  /* Buttons */
  .btn-group { display: flex; gap: 8px; flex-wrap: wrap; }
  .btn {
    padding: 8px 20px; border: none; border-radius: 8px; cursor: pointer;
    font-size: 14px; font-weight: 600; transition: all .2s;
    display: inline-flex; align-items: center; gap: 6px;
  }
  .btn:active { transform: scale(.96); }
  .btn:disabled { opacity: .4; cursor: not-allowed; transform: none; }
  .btn-primary { background: var(--primary); color: #fff; }
  .btn-primary:hover:not(:disabled) { background: var(--primary-dim); }
  .btn-success { background: var(--green); color: #1a1b2e; }
  .btn-success:hover:not(:disabled) { filter: brightness(1.1); }
  .btn-danger { background: var(--red); color: #fff; }
  .btn-danger:hover:not(:disabled) { filter: brightness(1.1); }
  .btn-warning { background: var(--yellow); color: #1a1b2e; }
  .btn-warning:hover:not(:disabled) { filter: brightness(1.1); }
  .btn-sm { padding: 5px 12px; font-size: 12px; }

  /* Grid */
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }

  /* Card */
  .card {
    background: var(--card); border-radius: var(--radius); padding: 20px;
    box-shadow: var(--shadow);
  }
  .card h3 {
    font-size: 14px; color: var(--text-dim); text-transform: uppercase;
    letter-spacing: .5px; margin-bottom: 12px; display: flex;
    align-items: center; gap: 8px;
  }

  /* QR Code */
  .qr-area {
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; min-height: 200px;
  }
  .qr-area img {
    width: 200px; height: 200px; border-radius: 8px;
    image-rendering: pixelated;
  }
  .qr-placeholder {
    width: 200px; height: 200px; border-radius: 8px;
    background: var(--bg); display: flex; align-items: center;
    justify-content: center; color: var(--text-dim); font-size: 14px;
    border: 2px dashed var(--border); text-align: center; padding: 20px;
  }

  /* Config */
  .config-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 0; border-bottom: 1px solid var(--border);
  }
  .config-row:last-child { border-bottom: none; }
  .config-label { font-size: 14px; color: var(--text); }
  .config-label small { color: var(--text-dim); display: block; font-size: 12px; }
  .config-input {
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 6px 10px; color: var(--text); font-size: 13px; width: 140px;
    transition: border .2s;
  }
  .config-input:focus { outline: none; border-color: var(--primary); }

  /* Logs */
  .log-area {
    background: #0d0e1a; border-radius: 8px; padding: 16px;
    height: 280px; overflow-y: auto; font-family: 'Cascadia Code', 'Fira Code', monospace;
    font-size: 12px; line-height: 1.6;
  }
  .log-area::-webkit-scrollbar { width: 4px; }
  .log-area::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
  .log-entry { color: var(--text-dim); }
  .log-entry:nth-child(odd) { color: var(--text); }
  .log-empty { color: var(--text-dim); text-align: center; padding: 60px 0; }

  /* Toast */
  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: var(--card); color: var(--text); padding: 12px 24px;
    border-radius: 8px; box-shadow: var(--shadow); font-size: 14px;
    opacity: 0; transition: all .3s; z-index: 999;
    border: 1px solid var(--border);
  }
  .toast.show { opacity: 1; bottom: 32px; }

  /* Progress */
  .progress-bar {
    display: flex; gap: 6px; align-items: center;
    margin-top: 8px;
  }
  .progress-step {
    padding: 3px 10px; border-radius: 12px; font-size: 11px;
    background: var(--border); color: var(--text-dim);
    transition: all .3s;
  }
  .progress-step.active { background: var(--yellow); color: #1a1b2e; }
  .progress-step.done { background: var(--green); color: #1a1b2e; }
  .progress-step.fail { background: var(--red); color: #fff; }

  footer {
    text-align: center; color: var(--text-dim); font-size: 12px;
    padding: 20px 0; border-top: 1px solid var(--border); margin-top: 24px;
  }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🐱 <span>猫娘 Bot</span> 管理面板</h1>
    <p>一键管理你的 QQ AI 机器人</p>
  </header>

  <!-- 状态栏 -->
  <div class="status-bar">
    <div class="status-row">
      <div style="display:flex;gap:24px;flex-wrap:wrap">
        <div class="status-item">
          <div class="status-dot" id="napcatDot"></div>
          <div><div class="status-label">NapCat</div><div class="status-value" id="napcatText">检测中</div></div>
        </div>
        <div class="status-item">
          <div class="status-dot" id="botDot"></div>
          <div><div class="status-label">Bot</div><div class="status-value" id="botText">检测中</div></div>
        </div>
        <div class="status-item">
          <div class="status-dot" id="wsDot"></div>
          <div><div class="status-label">WebSocket</div><div class="status-value" id="wsText">检测中</div></div>
        </div>
      </div>
      <div class="btn-group">
        <button class="btn btn-success" id="btnStart" onclick="startAll()">▶ 一键启动</button>
        <button class="btn btn-danger" id="btnStop" onclick="stopAll()">■ 全部停止</button>
        <button class="btn btn-warning" id="btnRestart" onclick="restartAll()">↻ 重启</button>
      </div>
    </div>
    <div class="status-details">
      <span id="stageText">状态：空闲</span>
      <span id="pidText"></span>
    </div>
    <div class="progress-bar" id="progressBar">
      <span class="progress-step" id="stepNapcat">① NapCat</span>
      <span style="color:var(--text-dim)">→</span>
      <span class="progress-step" id="stepQr">② 二维码</span>
      <span style="color:var(--text-dim)">→</span>
      <span class="progress-step" id="stepWs">③ WebSocket</span>
      <span style="color:var(--text-dim)">→</span>
      <span class="progress-step" id="stepBot">④ Bot 运行</span>
    </div>
  </div>

  <div class="grid">
    <!-- 二维码 -->
    <div class="card">
      <h3>📱 扫码登录 QQ</h3>
      <div class="qr-area">
        <div id="qrContainer">
          <div class="qr-placeholder">点击「一键启动」<br>二维码会自动出现</div>
        </div>
      </div>
    </div>

    <!-- 快速配置 -->
    <div class="card">
      <h3>⚙️ 快速配置</h3>
      <div class="config-row">
        <div class="config-label">模型 <small>deepseek-v4-flash / pro</small></div>
        <input class="config-input" id="cfgModel" value="deepseek-chat" />
      </div>
      <div class="config-row">
        <div class="config-label">Temperature <small>0~1，越高越灵活</small></div>
        <input class="config-input" id="cfgTemp" value="0.7" type="number" step="0.1" min="0" max="1" />
      </div>
      <div class="config-row">
        <div class="config-label">Bot 名字 <small>群聊触发词</small></div>
        <input class="config-input" id="cfgName" value="猫娘" />
      </div>
      <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-primary btn-sm" onclick="saveConfig()">💾 保存</button>
        <button class="btn btn-sm" onclick="startNapcatOnly()" style="background:var(--border);color:var(--text)">只启动 NapCat</button>
        <button class="btn btn-sm" onclick="startBotOnly()" style="background:var(--border);color:var(--text)">只启动 Bot</button>
      </div>
    </div>
  </div>

  <!-- 日志 -->
  <div class="card">
    <h3>📋 运行日志</h3>
    <div class="log-area" id="logArea">
      <div class="log-empty">🐱 等待启动...</div>
    </div>
  </div>

  <footer>猫娘 Bot · 用 💕 和 🐱 制作</footer>
</div>

<div class="toast" id="toast"></div>

<script>
let statusTimer = null;

async function api(url, method='GET', body=null) {
  const opt = { method, headers: {} };
  if (body) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  return r.json();
}

function showToast(msg, ok=true) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.borderColor = ok ? 'var(--green)' : 'var(--red)';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ── 状态刷新 ──
function setDot(id, on) {
  document.getElementById(id).className = 'status-dot' + (on ? ' on' : '');
}

async function refreshStatus() {
  const data = await api('/api/status');

  setDot('napcatDot', data.napcat_running);
  document.getElementById('napcatText').textContent = data.napcat_running ? '运行中' : '已停止';
  setDot('botDot', data.bot_running);
  document.getElementById('botText').textContent = data.bot_running ? '运行中' : '已停止';
  setDot('wsDot', data.ws_ready);
  document.getElementById('wsText').textContent = data.ws_ready ? '已就绪' : '等待中';

  document.getElementById('btnStart').disabled = data.bot_running;
  document.getElementById('btnStop').disabled = !data.napcat_running && !data.bot_running;
  document.getElementById('pidText').textContent = data.pid ? `PID: ${data.pid}` : '';

  // 阶段文本
  const stageMap = {
    idle: '空闲', napcat: '⏳ 启动 NapCat 中...',
    qr: '📱 二维码已生成，请扫码', websocket: '✅ WebSocket 就绪',
    ready: '✅ NapCat 就绪，等待启动 Bot', bot_running: '🟢 运行中'
  };
  document.getElementById('stageText').textContent = '状态：' + (stageMap[data.stage] || data.stage);

  // 进度条
  const steps = ['stepNapcat', 'stepQr', 'stepWs', 'stepBot'];
  const stageOrder = ['napcat', 'qr', 'websocket', 'ready', 'bot_running'];
  const idx = stageOrder.indexOf(data.stage);
  steps.forEach((s, i) => {
    const el = document.getElementById(s);
    el.className = 'progress-step';
    if (i < idx) el.classList.add('done');
    else if (i === idx) el.classList.add('active');
  });
  if (data.stage === 'bot_running') {
    steps.forEach(s => document.getElementById(s).classList.add('done'));
  }

  // 二维码
  const qrContainer = document.getElementById('qrContainer');
  if (data.qr_exists) {
    qrContainer.innerHTML = `<img src="/api/qrcode?t=${Date.now()}" alt="二维码" />`;
  } else if (data.stage !== 'idle') {
    qrContainer.innerHTML = '<div class="qr-placeholder">⏳ 等待二维码生成...</div>';
  } else {
    qrContainer.innerHTML = '<div class="qr-placeholder">点击「一键启动」<br>二维码会自动出现</div>';
  }
}

async function refreshLogs() {
  const data = await api('/api/logs');
  const area = document.getElementById('logArea');
  if (!data.logs || data.logs.length === 0) {
    area.innerHTML = '<div class="log-empty">🐱 等待启动...</div>';
    return;
  }
  area.innerHTML = data.logs.map(l => '<div class="log-entry">' + escapeHtml(l) + '</div>').join('');
  area.scrollTop = area.scrollHeight;
}

async function refreshConfig() {
  const data = await api('/api/config');
  if (data.model) document.getElementById('cfgModel').value = data.model;
  if (data.temperature !== undefined) document.getElementById('cfgTemp').value = data.temperature;
  if (data.BOT_NAME) document.getElementById('cfgName').value = data.BOT_NAME;
}

function escapeHtml(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

// ── 操作 ──
async function startAll() {
  const data = await api('/api/start', 'POST', {});
  showToast(data.message || '启动中...');
}

async function stopAll() {
  const data = await api('/api/stop', 'POST', {});
  showToast(data.message || '已停止');
}

async function restartAll() {
  document.getElementById('btnRestart').disabled = true;
  document.getElementById('btnRestart').textContent = '⋯ 重启中';
  const data = await api('/api/restart', 'POST', {});
  showToast('重启中...');
  document.getElementById('btnRestart').disabled = false;
  document.getElementById('btnRestart').textContent = '↻ 重启';
}

async function startNapcatOnly() {
  const data = await api('/api/start-napcat', 'POST', {});
  showToast(data.message || '启动中...');
}

async function startBotOnly() {
  const data = await api('/api/start-bot', 'POST', {});
  showToast(data.message || '启动中...');
}

async function saveConfig() {
  const config = {
    model: document.getElementById('cfgModel').value.trim(),
    temperature: document.getElementById('cfgTemp').value.trim(),
    BOT_NAME: document.getElementById('cfgName').value.trim(),
  };
  if (config.model === 'deepseek-chat') delete config.model;
  const data = await api('/api/config', 'POST', { config });
  showToast(data.message || '已保存');
  refreshConfig();
}

// ── 定时刷新 ──
function startPolling() {
  refreshStatus(); refreshLogs(); refreshConfig();
  statusTimer = setInterval(() => { refreshStatus(); refreshLogs(); }, 2000);
}

window.onload = startPolling;
</script>
</body>
</html>"""


# ── 启动入口 ──

def main():
    # 加载当前配置
    global _env_config
    _env_config = load_env()
    add_log("🐱 猫娘 Bot 管理面板已启动")
    add_log(f"🌐 访问地址：http://{HOST}:{PORT}")

    server = HTTPServer((HOST, PORT), DashboardHandler)
    print(f"""
╔══════════════════════════════════════╗
║   🐱 猫娘 Bot 管理面板              ║
║                                      ║
║   🌐 http://{HOST}:{PORT}              ║
║                                      ║
║   按 Ctrl+C 停止面板                 ║
╚══════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹ 正在关闭面板...")
        if _bot_process:
            stop_bot()
        server.shutdown()
        print("👋 已退出")


if __name__ == "__main__":
    main()
