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

# ── Bot 进程管理 ──
_bot_process: subprocess.Popen | None = None
_bot_logs: list[str] = []
_log_lock = threading.Lock()
_env_config: dict[str, str] = {}


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
    """获取 Bot 运行状态"""
    global _bot_process
    if _bot_process is None:
        return {"running": False, "pid": None}
    ret = _bot_process.poll()
    if ret is not None:
        _bot_process = None
        return {"running": False, "pid": None, "exit_code": ret}
    return {"running": True, "pid": _bot_process.pid}


def start_bot() -> str:
    """启动 Bot"""
    global _bot_process
    status = get_bot_status()
    if status["running"]:
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

        # 启动日志读取线程
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
        add_log(f"❌ 启动失败：{e}")
        return f"❌ 启动失败：{e}"


def stop_bot() -> str:
    """停止 Bot"""
    global _bot_process
    status = get_bot_status()
    if not status["running"]:
        return "Bot 当前没有运行喵~"

    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(status["pid"])],
                           capture_output=True, timeout=5)
        else:
            os.kill(status["pid"], signal.SIGTERM)
        _bot_process = None
        add_log("⏹ Bot 已停止")
        return "✅ Bot 已停止"
    except Exception as e:
        add_log(f"❌ 停止失败：{e}")
        return f"❌ 停止失败：{e}"


def restart_bot() -> str:
    """重启 Bot"""
    msg = stop_bot()
    time.sleep(1)
    msg2 = start_bot()
    return f"{msg}\n{msg2}"


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
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len else "{}"
        data = json.loads(body) if body else {}

        if path == "/api/start":
            msg = start_bot()
            self._json_response({"message": msg, "status": get_bot_status()})
        elif path == "/api/stop":
            msg = stop_bot()
            self._json_response({"message": msg, "status": get_bot_status()})
        elif path == "/api/restart":
            msg = restart_bot()
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
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: var(--shadow); margin-bottom: 20px;
    flex-wrap: wrap; gap: 12px;
  }
  .status-left { display: flex; align-items: center; gap: 12px; }
  .status-dot {
    width: 14px; height: 14px; border-radius: 50%;
    background: var(--red); transition: all .3s;
    box-shadow: 0 0 8px var(--red);
  }
  .status-dot.running { background: var(--green); box-shadow: 0 0 8px var(--green); }
  .status-text { font-size: 16px; font-weight: 600; }
  .status-pid { color: var(--text-dim); font-size: 13px; }

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

  /* Grid */
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
  @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }

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
    padding: 6px 10px; color: var(--text); font-size: 13px; width: 160px;
    transition: border .2s;
  }
  .config-input:focus { outline: none; border-color: var(--primary); }

  /* Logs */
  .log-area {
    background: #0d0e1a; border-radius: 8px; padding: 16px;
    height: 320px; overflow-y: auto; font-family: 'Cascadia Code', 'Fira Code', monospace;
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

  /* Footer */
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
    <div class="status-left">
      <div class="status-dot" id="statusDot"></div>
      <div>
        <div class="status-text" id="statusText">检测中...</div>
        <div class="status-pid" id="statusPid"></div>
      </div>
    </div>
    <div class="btn-group">
      <button class="btn btn-success" id="btnStart" onclick="startBot()">▶ 启动</button>
      <button class="btn btn-danger" id="btnStop" onclick="stopBot()">■ 停止</button>
      <button class="btn btn-warning" id="btnRestart" onclick="restartBot()">↻ 重启</button>
    </div>
  </div>

  <div class="grid">
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
      <div style="margin-top:12px;text-align:right">
        <button class="btn btn-primary" onclick="saveConfig()">💾 保存配置</button>
      </div>
    </div>

    <!-- 快捷操作 -->
    <div class="card">
      <h3>🔗 快速链接</h3>
      <div style="display:flex;flex-direction:column;gap:8px">
        <a href="https://platform.deepseek.com" target="_blank" class="btn btn-primary" style="text-decoration:none;justify-content:center">
          🔑 DeepSeek 控制台
        </a>
        <a href="https://github.com/nico10086/-bot" target="_blank" class="btn" style="text-decoration:none;justify-content:center;background:var(--border);color:var(--text)">
          📦 GitHub 仓库
        </a>
        <button class="btn" onclick="openEnvFile()" style="background:var(--border);color:var(--text);justify-content:center">
          📝 编辑 .env 文件
        </button>
      </div>
    </div>
  </div>

  <!-- 日志 -->
  <div class="card">
    <h3>📋 运行日志</h3>
    <div class="log-area" id="logArea">
      <div class="log-empty">🐱 等待 Bot 启动...</div>
    </div>
  </div>

  <footer>
    猫娘 Bot · 用 💕 和 🐱 制作
  </footer>
</div>

<div class="toast" id="toast"></div>

<script>
let statusTimer = null;

// ── API 调用 ──
async function api(url, method='GET', body=null) {
  const opt = { method, headers: {} };
  if (body) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
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

// ── 状态 ──
async function refreshStatus() {
  const data = await api('/api/status');
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  const pid = document.getElementById('statusPid');
  const btnStart = document.getElementById('btnStart');
  const btnStop = document.getElementById('btnStop');
  const btnRestart = document.getElementById('btnRestart');

  if (data.running) {
    dot.className = 'status-dot running';
    text.textContent = '🟢 运行中';
    pid.textContent = `PID: ${data.pid}`;
    btnStart.disabled = true;
    btnStop.disabled = false;
    btnRestart.disabled = false;
  } else {
    dot.className = 'status-dot';
    text.textContent = '🔴 已停止';
    pid.textContent = data.exit_code !== undefined ? `退出码: ${data.exit_code}` : '';
    btnStart.disabled = false;
    btnStop.disabled = true;
    btnRestart.disabled = true;
  }
}

async function refreshLogs() {
  const data = await api('/api/logs');
  const area = document.getElementById('logArea');
  if (!data.logs || data.logs.length === 0) {
    area.innerHTML = '<div class="log-empty">🐱 等待 Bot 启动...</div>';
    return;
  }
  area.innerHTML = data.logs.map(l => `<div class="log-entry">${escapeHtml(l)}</div>`).join('');
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
async function startBot() {
  const data = await api('/api/start', 'POST', {});
  showToast(data.message || '已启动');
  refreshStatus();
}

async function stopBot() {
  const data = await api('/api/stop', 'POST', {});
  showToast(data.message || '已停止');
  refreshStatus();
}

async function restartBot() {
  const btn = document.getElementById('btnRestart');
  btn.disabled = true;
  btn.textContent = '⋯ 重启中';
  const data = await api('/api/restart', 'POST', {});
  showToast(data.message || '已重启');
  btn.textContent = '↻ 重启';
  refreshStatus();
}

async function saveConfig() {
  const config = {
    model: document.getElementById('cfgModel').value.trim(),
    temperature: document.getElementById('cfgTemp').value.trim(),
    BOT_NAME: document.getElementById('cfgName').value.trim(),
  };
  // 如果 model 是 deepseek-chat，移除这个字段（用代码默认值）
  if (config.model === 'deepseek-chat') delete config.model;

  const data = await api('/api/config', 'POST', { config });
  showToast(data.message || '配置已保存');
  refreshConfig();
}

function openEnvFile() {
  // 通过 api 获取路径信息
  window.open('https://github.com/nico10086/-bot', '_blank');
  showToast('请在项目目录下手动编辑 .env 文件');
}

// ── 定时刷新 ──
function startPolling() {
  refreshStatus();
  refreshLogs();
  refreshConfig();
  statusTimer = setInterval(() => {
    refreshStatus();
    refreshLogs();
  }, 2000);
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
