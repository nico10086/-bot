"""
🐱 猫娘 Bot 桌面管理程序
一键启动 / 停止 / 重启，托盘后台运行
用法：双击运行或在终端执行 python bot_app.py
"""
import os
import sys
import json
import subprocess
import threading
import time
import signal
import io
import tkinter as tk
from tkinter import scrolledtext, font, messagebox
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont, ImageTk
import pystray
import winreg

# ── 配置 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NAPCAT_DIR = os.path.join(BASE_DIR, "NapCat.Shell")
NAPCAT_LAUNCHER = os.path.join(NAPCAT_DIR, "NapCatWinBootMain.exe")
NAPCAT_INJECT = os.path.join(NAPCAT_DIR, "NapCatWinBootHook.dll")
NAPCAT_MAIN = os.path.join(NAPCAT_DIR, "napcat.mjs")
NAPCAT_PATCH = os.path.join(NAPCAT_DIR, "qqnt.json")
NAPCAT_LOAD_JS = os.path.join(NAPCAT_DIR, "loadNapCat.js")
QR_PATH = os.path.join(NAPCAT_DIR, "cache", "qrcode.png")
ENV_PATH = os.path.join(BASE_DIR, ".env")
BOT_SCRIPT = os.path.join(BASE_DIR, "qq_bot_standalone.py")

# ── 全局状态 ──
_napcat_process: subprocess.Popen | None = None
_bot_process: subprocess.Popen | None = None
_ws_ready: bool = False
_startup_stage: str = "idle"
_log_lines: list[str] = []
_log_lock = threading.Lock()
_tray_icon: pystray.Icon | None = None
_main_window: tk.Tk | None = None
_minimize_choice: str | None = None  # "tray"=最小化到托盘, "quit"=退出, None=未选择


# ============================================================
#  日志
# ============================================================
def add_log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    with _log_lock:
        _log_lines.append(f"[{ts}] {msg}")
        if len(_log_lines) > 500:
            _log_lines[:100] = []


# ============================================================
#  工具函数
# ============================================================
def load_env() -> dict[str, str]:
    cfg = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    cfg[k.strip()] = v.strip()
    return cfg


def find_qq_path() -> str | None:
    for subkey in (
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
    ):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey)
            val, _ = winreg.QueryValueEx(key, "UninstallString")
            winreg.CloseKey(key)
            # 注册表值可能带引号，需要去除
            val = val.strip('\"').strip()
            qq_path = os.path.join(os.path.dirname(val), "QQ.exe")
            if os.path.exists(qq_path):
                return qq_path
        except Exception:
            continue
    return None


# ============================================================
#  NapCat 管理
# ============================================================
def start_napcat() -> str:
    global _napcat_process, _startup_stage, _ws_ready
    if _napcat_process and _napcat_process.poll() is None:
        return "NapCat 已在运行"

    qq_path = find_qq_path()
    if not qq_path:
        return "❌ 找不到 QQ.exe，请确认已安装 QQNT"

    add_log(f"🔍 找到 QQ: {qq_path}")
    add_log("🚀 启动 NapCat...")

    main_path = NAPCAT_MAIN.replace("\\", "/")
    with open(NAPCAT_LOAD_JS, "w", encoding="utf-8") as f:
        f.write(f'(async () => {{await import("file:///{main_path}")}})()\n')

    if os.path.exists(QR_PATH):
        os.remove(QR_PATH)

    env = os.environ.copy()
    env["NAPCAT_PATCH_PACKAGE"] = NAPCAT_PATCH
    env["NAPCAT_LOAD_PATH"] = NAPCAT_LOAD_JS
    env["NAPCAT_INJECT_PATH"] = NAPCAT_INJECT
    env["NAPCAT_LAUNCHER_PATH"] = NAPCAT_LAUNCHER

    try:
        _napcat_process = subprocess.Popen(
            [NAPCAT_LAUNCHER, qq_path, NAPCAT_INJECT],
            cwd=NAPCAT_DIR, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        _startup_stage = "napcat"
        _ws_ready = False
        add_log("✅ NapCat 已启动，等待二维码...")

        def monitor():
            global _startup_stage, _ws_ready
            qr_done = False
            for i in range(120):
                time.sleep(1)
                if not qr_done and os.path.exists(QR_PATH):
                    qr_done = True
                    _startup_stage = "qr"
                    add_log(f"📱 二维码已生成")
                    # 自动弹出二维码图片（像 start_bot.bat 一样）
                    try:
                        os.startfile(QR_PATH)
                        add_log("🖼️ 已自动打开二维码图片，请用手机 QQ 扫码")
                    except Exception:
                        add_log("⚠️ 无法自动打开二维码，请手动打开 NapCat.Shell\\cache\\qrcode.png")
                    _update_status()
                if not _ws_ready:
                    try:
                        r = subprocess.run(["netstat", "-an"],
                                           capture_output=True, text=True, timeout=5)
                        if ":8080" in r.stdout and "LISTENING" in r.stdout:
                            _ws_ready = True
                            _startup_stage = "websocket"
                            add_log("✅ WebSocket 8080 已就绪")
                            _update_status()
                    except Exception:
                        pass
                if _ws_ready:
                    _startup_stage = "ready"
                    _update_status()
                    break

        threading.Thread(target=monitor, daemon=True).start()
        return "✅ NapCat 已启动"
    except Exception as e:
        add_log(f"❌ NapCat 启动失败: {e}")
        return f"❌ NapCat 启动失败: {e}"


def stop_napcat():
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


# ============================================================
#  Bot 管理
# ============================================================
def start_bot() -> str:
    global _bot_process
    if _bot_process and _bot_process.poll() is None:
        return "Bot 已在运行"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        _bot_process = subprocess.Popen(
            [sys.executable, BOT_SCRIPT], cwd=BASE_DIR, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        add_log("🚀 Bot 已启动")

        def read_out():
            global _bot_process
            try:
                for line in iter(_bot_process.stdout.readline, ""):
                    if line:
                        add_log(line.rstrip("\n\r"))
            except Exception:
                pass
            add_log("⏹ Bot 进程已退出")
            _update_status()

        threading.Thread(target=read_out, daemon=True).start()
        return "✅ Bot 启动成功"
    except Exception as e:
        add_log(f"❌ Bot 启动失败: {e}")
        return f"❌ Bot 启动失败: {e}"


def stop_bot():
    global _bot_process
    if _bot_process and _bot_process.poll() is None:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(_bot_process.pid)],
                           capture_output=True, timeout=5)
        except Exception:
            pass
        _bot_process = None
        add_log("⏹ Bot 已停止")


# ============================================================
#  一键操作
# ============================================================
def start_all():
    if _bot_process and _bot_process.poll() is None:
        add_log("🐱 猫娘已经在运行了喵~")
        return
    r = start_napcat()
    add_log(r)

    def auto_bot():
        for _ in range(150):
            time.sleep(1)
            if _ws_ready:
                time.sleep(2)
                r2 = start_bot()
                add_log(r2)
                _update_status()
                _startup_stage = "bot_running"
                return
        add_log("⏱ NapCat 启动超时")
    threading.Thread(target=auto_bot, daemon=True).start()


def stop_all():
    stop_bot()
    time.sleep(0.5)
    stop_napcat()
    _update_status()


def restart_all():
    add_log("↻ 正在重启...")
    stop_all()
    time.sleep(2)
    start_all()


# ============================================================
#  状态
# ============================================================
def get_status() -> dict:
    napcat_on = _napcat_process is not None and _napcat_process.poll() is None
    bot_on = _bot_process is not None and _bot_process.poll() is None
    return {
        "napcat": napcat_on,
        "bot": bot_on,
        "ws": _ws_ready,
        "stage": _startup_stage,
        "qr": os.path.exists(QR_PATH),
    }


def _update_status():
    """在主线程更新 GUI 状态"""
    if _main_window:
        try:
            _main_window.after(0, _refresh_ui)
        except Exception:
            pass


# ============================================================
#  生成系统托盘图标
# ============================================================
def create_tray_image() -> Image.Image:
    """生成一个 64x64 的猫爪图标"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 粉色猫爪
    pink = (244, 114, 182, 255)
    # 肉垫
    draw.ellipse([12, 24, 28, 40], fill=pink)
    draw.ellipse([36, 24, 52, 40], fill=pink)
    draw.ellipse([8, 16, 24, 32], fill=pink)
    draw.ellipse([40, 16, 56, 32], fill=pink)
    # 中心肉垫
    draw.ellipse([22, 28, 42, 48], fill=(252, 168, 210, 255))
    # 眼睛
    draw.ellipse([20, 8, 26, 14], fill=(30, 30, 30, 255))
    draw.ellipse([38, 8, 44, 14], fill=(30, 30, 30, 255))
    return img


def on_tray_show(icon, item):
    icon.stop()
    if _main_window:
        _main_window.after(0, _main_window.deiconify)
        _main_window.after(0, _main_window.lift)


def on_tray_start(icon, item):
    if _main_window:
        _main_window.after(0, start_all)


def on_tray_stop(icon, item):
    if _main_window:
        _main_window.after(0, stop_all)


def on_tray_quit(icon, item):
    icon.stop()
    if _main_window:
        _main_window.after(0, _quit_app)


def setup_tray():
    global _tray_icon
    menu = pystray.Menu(
        pystray.MenuItem("🐱 显示窗口", on_tray_show, default=True),
        pystray.MenuItem("▶ 一键启动", on_tray_start),
        pystray.MenuItem("■ 全部停止", on_tray_stop),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🚪 退出", on_tray_quit),
    )
    _tray_icon = pystray.Icon(
        "catgirl_bot", create_tray_image(),
        "🐱 猫娘 Bot", menu
    )
    _tray_icon.run()


# ============================================================
#  Tkinter GUI
# ============================================================
class BotApp:
    def __init__(self):
        global _main_window
        self.root = tk.Tk()
        _main_window = self.root
        self.root.title("🐱 猫娘 Bot")
        self.root.geometry("680x620")
        self.root.minsize(600, 500)
        self.root.configure(bg="#1a1b2e")

        # 设置图标
        try:
            self.root.iconphoto(True, tk.PhotoImage(data=self._icon_data()))
        except Exception:
            pass

        # 拦截关闭按钮 → 隐藏到托盘
        self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)

        # 配色
        self.BG = "#1a1b2e"
        self.CARD = "#232545"
        self.PINK = "#f472b6"
        self.GREEN = "#34d399"
        self.RED = "#f87171"
        self.YELLOW = "#fbbf24"
        self.TEXT = "#e2e8f0"
        self.TEXT_DIM = "#94a3b8"
        self.BORDER = "#334155"
        self.FONT = ("Microsoft YaHei UI", 10)
        self.FONT_SM = ("Microsoft YaHei UI", 9)
        self.FONT_MONO = ("Cascadia Code", 10)

        self._build_ui()
        self._refresh_timer()

    def _icon_data(self):
        """返回一个简单的粉色猫爪 PhotoImage base64"""
        # 最小尺寸的图标
        return "R0lGODlhEAAQAKIFAP7+/pSYmHB08P///wAAAAAAAAAAACH5BAEAAAUALAAAAAAQABAAAANCWLpJBgMAACH5BAEAAAUALAAAAAAQABAAAANCWLpJBgMAACH5BAEAAAUALAAAAAAQABAAAANCWLpJBgMAACH5BAEAAAUALAAAAAAQABAAAANCWLpJBgMAACH5BAEAAAUALAAAAAAQABAAAANCWLpJBgMAACH5BAEAAAUALAAAAAAQABAAAANCWLpJBgMAACH5BAEAAAUALAAAAAAQABAAAANCWLpJBgMA"

    def _build_ui(self):
        root = self.root

        # ── 标题 ──
        title_frame = tk.Frame(root, bg=self.BG)
        title_frame.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(title_frame, text="🐱 猫娘 Bot",
                 font=("Microsoft YaHei UI", 20, "bold"),
                 fg=self.PINK, bg=self.BG).pack()
        tk.Label(title_frame, text="一键管理你的 QQ AI 机器人",
                 font=self.FONT_SM, fg=self.TEXT_DIM, bg=self.BG).pack()

        # ── 状态栏 ──
        self._build_status_bar(root)

        # ── 按钮栏 ──
        self._build_buttons(root)

        # ── 二维码 + 日志 左右布局 ──
        bottom = tk.Frame(root, bg=self.BG)
        bottom.pack(fill="both", expand=True, padx=20, pady=8)

        self._build_qrcode(bottom)
        self._build_log(bottom)

    def _build_status_bar(self, parent):
        frame = tk.Frame(parent, bg=self.CARD, padx=16, pady=12)
        frame.pack(fill="x", padx=20, pady=8)

        # 用一个 Canvas 模拟卡片圆角
        self.status_vars = {}
        items = [("napcat", "NapCat"), ("bot", "Bot"), ("ws", "WebSocket")]
        for i, (key, label) in enumerate(items):
            if i > 0:
                tk.Frame(frame, width=1, bg=self.BORDER).pack(side="left", fill="y", padx=12)
            sub = tk.Frame(frame, bg=self.CARD)
            sub.pack(side="left")
            dot = tk.Canvas(sub, width=12, height=12, bg=self.CARD,
                            highlightthickness=0)
            dot.pack(side="left", padx=(0, 8))
            self.status_vars[key] = dot
            tk.Label(sub, text=label, font=self.FONT_SM, fg=self.TEXT_DIM, bg=self.CARD).pack()
            val_label = tk.Label(sub, text="检测中", font=self.FONT, fg=self.TEXT, bg=self.CARD)
            val_label.pack()
            self.status_vars[f"{key}_text"] = val_label

        tk.Frame(frame, width=1, bg=self.BORDER).pack(side="left", fill="y", padx=12)
        self.stage_label = tk.Label(frame, text="状态：空闲",
                                    font=self.FONT_SM, fg=self.TEXT_DIM, bg=self.CARD)
        self.stage_label.pack(side="left")

    def _build_buttons(self, parent):
        frame = tk.Frame(parent, bg=self.BG)
        frame.pack(fill="x", padx=20, pady=8)

        btn_style = {"font": ("Microsoft YaHei UI", 11, "bold"),
                     "border": "0", "cursor": "hand2", "padx": 20, "pady": 8}

        self.btn_start = tk.Button(frame, text="▶ 一键启动", bg=self.GREEN, fg="#1a1b2e",
                                   command=lambda: threading.Thread(target=start_all, daemon=True).start(),
                                   **btn_style)
        self.btn_start.pack(side="left", padx=(0, 8))

        self.btn_stop = tk.Button(frame, text="■ 全部停止", bg=self.RED, fg="white",
                                  command=lambda: threading.Thread(target=stop_all, daemon=True).start(),
                                  **btn_style)
        self.btn_stop.pack(side="left", padx=(0, 8))

        self.btn_restart = tk.Button(frame, text="↻ 重启", bg=self.YELLOW, fg="#1a1b2e",
                                     command=lambda: threading.Thread(target=restart_all, daemon=True).start(),
                                     **btn_style)
        self.btn_restart.pack(side="left", padx=(0, 8))

        # 单独启动按钮
        self.btn_napcat = tk.Button(frame, text="启动 NapCat", bg=self.BORDER, fg=self.TEXT,
                                    font=self.FONT_SM,
                                    command=lambda: threading.Thread(target=lambda: add_log(start_napcat()), daemon=True).start())
        self.btn_napcat.pack(side="right", padx=(4, 0))

        self.btn_bot_only = tk.Button(frame, text="启动 Bot", bg=self.BORDER, fg=self.TEXT,
                                      font=self.FONT_SM,
                                      command=lambda: threading.Thread(target=lambda: add_log(start_bot()), daemon=True).start())
        self.btn_bot_only.pack(side="right", padx=(4, 0))

    def _build_qrcode(self, parent):
        """二维码显示区域（左侧）"""
        frame = tk.Frame(parent, bg=self.CARD, padx=12, pady=10)
        frame.pack(side="left", fill="y", padx=(0, 8))

        tk.Label(frame, text="📱 扫码登录 QQ", font=self.FONT,
                 fg=self.TEXT_DIM, bg=self.CARD).pack(anchor="w")

        self.qr_label = tk.Label(frame, text="点击「一键启动」\n二维码会自动出现",
                                  font=self.FONT, fg=self.TEXT_DIM,
                                  bg="#0d0e1a", width=18, height=8,
                                  relief="solid", bd=0)
        self.qr_label.pack(pady=(6, 0))

        # 实际二维码图片（默认隐藏）
        self.qr_image_label = tk.Label(frame, bg="#0d0e1a")
        # 不 pack，检测到二维码后再显示

    def _build_log(self, parent):
        frame = tk.Frame(parent, bg=self.CARD, padx=12, pady=10)
        frame.pack(fill="both", expand=True, padx=20, pady=8)

        tk.Label(frame, text="📋 运行日志", font=self.FONT, fg=self.TEXT_DIM, bg=self.CARD).pack(anchor="w")

        self.log_area = scrolledtext.ScrolledText(
            frame, bg="#0d0e1a", fg=self.TEXT_DIM,
            font=self.FONT_MONO, insertbackground=self.TEXT,
            border=0, padx=10, pady=10, height=14,
            state="disabled", wrap="word",
        )
        self.log_area.pack(fill="both", expand=True, pady=(6, 0))
        # 颜色标签
        self.log_area.tag_config("info", foreground=self.TEXT_DIM)
        self.log_area.tag_config("ok", foreground=self.GREEN)
        self.log_area.tag_config("err", foreground=self.RED)
        self.log_area.tag_config("warn", foreground=self.YELLOW)

    # ── 状态刷新 ──
    def _refresh_ui(self):
        """刷新状态指示器和按钮"""
        s = get_status()
        # 状态点
        for key in ("napcat", "bot", "ws"):
            dot = self.status_vars[key]
            on = s[key] if key != "ws" else s["ws"]
            dot.delete("all")
            color = self.GREEN if on else self.RED
            dot.create_oval(1, 1, 11, 11, fill=color, outline="")
            if on:
                dot.create_oval(3, 3, 9, 9, fill=color, outline="")
            self.status_vars[f"{key}_text"].config(
                text="运行中" if on else "已停止")
        # 阶段
        stage_map = {
            "idle": "空闲", "napcat": "⏳ 启动 NapCat...",
            "qr": "📱 二维码已生成", "websocket": "✅ WebSocket 就绪",
            "ready": "✅ 就绪", "bot_running": "🟢 运行中",
        }
        self.stage_label.config(text="状态：" + stage_map.get(s["stage"], s["stage"]))
        # 按钮
        running = s["bot"]
        self.btn_start.config(state="disabled" if running else "normal")
        self.btn_stop.config(state="normal" if s["napcat"] or running else "disabled")
        self.btn_restart.config(state="disabled" if not s["napcat"] and not running else "normal")

        # 二维码显示
        if s["qr"]:
            self.qr_label.pack_forget()
            try:
                # 用 PIL 加载二维码并缩放显示
                pil_img = Image.open(QR_PATH)
                pil_img = pil_img.resize((180, 180), Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(pil_img)
                self.qr_image_label.config(image=tk_img)
                self.qr_image_label.image = tk_img  # 保持引用
                self.qr_image_label.pack(pady=(6, 0))
            except Exception:
                self.qr_label.config(text="二维码已生成\n但无法预览")
                self.qr_label.pack()
        elif s["stage"] != "idle":
            self.qr_image_label.pack_forget()
            self.qr_label.config(text="⏳ 等待二维码生成...")
            self.qr_label.pack()
        else:
            self.qr_image_label.pack_forget()
            self.qr_label.config(text="点击「一键启动」\n二维码会自动出现")
            self.qr_label.pack()

        # 日志
        with _log_lock:
            if _log_lines:
                self.log_area.config(state="normal")
                # 只追加新日志
                current_count = int(self.log_area.get("1.0", "end-1c").count("\n"))
                if current_count < len(_log_lines):
                    for line in _log_lines[current_count - 1 if current_count > 0 else 0:]:
                        tag = "info"
                        if "✅" in line or "已启动" in line or "成功" in line:
                            tag = "ok"
                        elif "❌" in line or "失败" in line or "错误" in line:
                            tag = "err"
                        elif "⚠️" in line or "超时" in line:
                            tag = "warn"
                        self.log_area.insert("end", line + "\n", tag)
                    self.log_area.see("end")
                    self.log_area.config(state="disabled")

    def _refresh_timer(self):
        """定时刷新"""
        self._refresh_ui()
        self.root.after(2000, self._refresh_timer)

    # ── 托盘 ──
    def _minimize_to_tray(self):
        global _minimize_choice
        # 第一次点击叉：询问用户
        if _minimize_choice is None:
            choice = tk.messagebox.askyesnocancel(
                title="🐱 猫娘 Bot",
                message=(
                    "点击「是」→ 最小化到系统托盘（后台继续运行）\n"
                    "点击「否」→ 完全关闭程序\n"
                    "点击「取消」→ 不操作\n\n"
                    "提示：选择最小化后，本次运行中再点叉会直接最小化。"
                ),
                icon="question",
            )
            if choice is None:  # 取消
                return
            elif choice:  # 是 → 最小化到托盘
                _minimize_choice = "tray"
            else:  # 否 → 完全退出
                _minimize_choice = "quit"
                _quit_app()
                return

        # 已经选择过：直接执行
        if _minimize_choice == "tray":
            self.root.withdraw()
            add_log("🐱 猫娘 Bot 已最小化到系统托盘")
            threading.Thread(target=setup_tray, daemon=True).start()
        else:  # quit
            _quit_app()

    def run(self):
        self.root.mainloop()


# ============================================================
#  退出
# ============================================================
def _quit_app():
    add_log("👋 正在退出...")
    stop_bot()
    stop_napcat()
    if _tray_icon:
        _tray_icon.stop()
    if _main_window:
        _main_window.destroy()
    os._exit(0)


# ============================================================
#  入口
# ============================================================
def main():
    add_log("🐱 猫娘 Bot 桌面版已启动")
    add_log(f"📂 工作目录: {BASE_DIR}")
    app = BotApp()
    app.run()


if __name__ == "__main__":
    main()
