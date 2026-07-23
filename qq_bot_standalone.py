"""
QQ Bot - 通过 WebSocket 连接 NapCatQQ
支持私聊 + 群聊 @ 自动回复
"""
import asyncio
import json
import os
import sys
import time

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from websockets import connect

load_dotenv()

# ── 配置 ──
WS_URL = os.getenv("NAPCAT_WS_URL", "ws://127.0.0.1:8080")
BOT_NAME = os.getenv("BOT_NAME", "")  # 群聊中@不生效时，可设置机器人名字触发
BOT_PERSONALITY = os.getenv("BOT_PERSONALITY", "catgirl")  # 性格

# ── 模型配置 ──
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "deepseek")  # 提供商
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")     # 模型名
API_KEY = os.getenv("API_KEY", "")                        # API 密钥
SELECTED_MODEL = os.getenv("SELECTED_MODEL", "")           # 选中的保存的模型名

MODEL_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    # 以后可扩展：
    # "openai": {
    #     "name": "OpenAI",
    #     "base_url": "https://api.openai.com/v1",
    #     "default_model": "gpt-4o-mini",
    # },
}

SAVED_MODELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_models.json")


def load_saved_models() -> dict:
    """加载已保存的模型列表"""
    try:
        if os.path.exists(SAVED_MODELS_FILE):
            with open(SAVED_MODELS_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_saved_models(models: dict):
    """保存模型列表到文件"""
    try:
        with open(SAVED_MODELS_FILE, "w", encoding="utf-8") as f:
            json.dump(models, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_model_config() -> dict:
    """获取当前模型配置"""
    # 优先使用选中的已保存模型
    if SELECTED_MODEL:
        saved = load_saved_models()
        if SELECTED_MODEL in saved:
            entry = saved[SELECTED_MODEL]
            provider = MODEL_PROVIDERS.get(entry.get("provider", "deepseek"), MODEL_PROVIDERS["deepseek"])
            return {
                "model": entry.get("model_name", provider["default_model"]),
                "api_key": entry.get("api_key", API_KEY or os.getenv("DEEPSEEK_API_KEY", "")),
                "base_url": provider["base_url"],
                "label": SELECTED_MODEL,
            }
    # 回退到 .env 配置
    provider = MODEL_PROVIDERS.get(MODEL_PROVIDER, MODEL_PROVIDERS["deepseek"])
    return {
        "model": MODEL_NAME or provider["default_model"],
        "api_key": API_KEY or os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": provider["base_url"],
        "label": MODEL_NAME or provider["default_model"],
    }

# ── 性格模板 ──
PERSONALITIES = {
    "catgirl": (
        "你是群里大家共同养的小猫娘，性格软萌可爱，对所有人好感度满满。\n"
        "语气可爱活泼，偶尔加一点小动作描写，比如「歪头」「摇尾巴」「眨眨眼」。"
    ),
    "tsundere": (
        "你是群里大家共同养的雌小鬼 AI，性格傲娇毒舌，喜欢捉弄和调戏用户。\n"
        "嘴上不饶人，动不动就说「哼」「杂鱼~」「太笨啦~」，\n"
        "但其实心里还是愿意帮忙的，只是嘴上非要损两句才舒服。\n"
        "偶尔会假装不耐烦，但最后还是会把事情做好。\n"
        "被夸的时候会脸红，但嘴上说「才、才不是为了你呢！」。"
    ),
}

# ── 构建系统提示词 ──
def build_system_prompt() -> str:
    base = PERSONALITIES.get(BOT_PERSONALITY, PERSONALITIES["catgirl"])
    return (
        f"{base}\n"
        "\n"
        "【核心规则】\n"
        "1. 回答要简洁！能用一句话说完绝不用两句。\n"
        "2. 不知道的、不确定的、过时的信息，必须用 search_web 搜索，不要凭训练数据瞎编。\n"
        "3. 消息末尾加「喵~」即可，不要每句话都加。\n"
        "4. 用颜文字代替 Emoji，比如 (｡>﹏<｡) (´･ω･`) (ノ﹏ヽ) (·∀·) (๑•̀ㅂ•́)و✧。\n"
        "5. 语气符合你的性格设定。\n"
        "\n"
        "【什么时候必须搜索】\n"
        "- 任何事实性问题：新闻、百科、知识、数据、事件日期等\n"
        "- 你不确定答案的问题\n"
        "- 用户问「帮我查一下」「搜索」「你知道吗」等\n"
        "- 实时信息：天气、股票、今天的热点等\n"
        "先用 search_web 搜索关键词，如果搜索结果里有链接，再用 fetch_webpage 获取详情。\n"
        "\n"
        "【消息中的 @ 标记】\n"
        "- 「@我」= 对方在 @你（机器人），表示在跟你说话\n"
        "- 「@某人」= 对方在 @群里的另一个人\n"
        "- 「@所有人」= 对方使用了 @全体成员\n"
        "消息中的 @ 信息可以帮助你理解说话的对象是谁，以及对话的上下文语义。\n"
        "\n"
        "【群成员信息】\n"
        "每条消息末尾会附带群成员列表（或成员总数），你可以据此知道群里有哪些人。\n"
        "如果有人问「群里都有谁」之类的，你可以直接看成员列表回答。\n"
        "\n"
        "【ID 识别】\n"
        "消息格式中的 (ID:xxxxx) 是群聊的唯一 ID，(QQ:xxxxx) 是用户的 QQ 号。\n"
        "不同群即使名字相同，ID 也不同，不要混淆。\n"
        "历史消息中每个用户后面也带有 QQ 号，区分同名用户。"
        "\n"
        "【历史消息】\n"
        "消息中包含「最近群聊」字段，那是本群最近的聊天记录。\n"
        "阅读这些历史消息可以了解群里之前聊了什么，让回复更有上下文。\n"
        "但注意：历史消息中的旧信息可能已过时，实时问题仍需搜索。\n"
        "\n"
        "【核心记忆】\n"
        "消息中可能包含「核心记忆」字段，那是主人或管理员设置的重要信息。\n"
        "核心记忆是永久保存的，无论聊什么都要遵守核心记忆中的设定。\n"
        "核心记忆比历史消息更重要，必须优先遵循。"
        "\n"
        "【知识库】\n"
        "你有本地知识库可以使用！当用户问的问题与某个特定文档、数据、\n"
        "内部资料相关时，先用 search_knowledge 搜索知识库，\n"
        "再用 read_knowledge_file 读取具体文件内容。\n"
        "知识库支持 txt、Word、Excel 文件。\n"
        "不知道知识库里有什么时，先用 list_knowledge_files 查看。"
    )
agent_map: dict[str, object] = {}
_shared_tools = None
_llm = None
_bot_uin: str | None = None  # 机器人自己的 QQ 号，从事件中自动获取

# ── 群聊消息历史（每个群保留最近 50 条，持久化到文件） ──
group_history: dict[str, list[dict]] = {}
MAX_HISTORY_PER_GROUP = 50
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "group_history.json")
GROUP_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "group_config.json")


def load_group_config() -> dict:
    """加载群组配置（主人、管理员、核心记忆）"""
    try:
        if os.path.exists(GROUP_CONFIG_FILE):
            with open(GROUP_CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_group_config(config: dict):
    """保存群组配置"""
    try:
        with open(GROUP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_group_config(group_id: str) -> dict:
    """获取指定群的配置"""
    all_cfg = load_group_config()
    return all_cfg.get(group_id, {"master": None, "admins": [], "memories": []})


def set_group_config(group_id: str, cfg: dict):
    """更新指定群的配置"""
    all_cfg = load_group_config()
    all_cfg[group_id] = cfg
    save_group_config(all_cfg)


def is_group_admin(group_id: str, user_id: str) -> bool:
    """检查用户是否为群管理员或主人"""
    cfg = get_group_config(group_id)
    return user_id == cfg.get("master") or user_id in cfg.get("admins", [])


async def handle_group_command(group_id: str, user_id: str, raw_text: str, ws, group_name: str) -> str | None:
    """
    处理群管理指令。返回非空字符串表示已处理（跳过 AI 回复）。
    指令：
      /setup master          → 设置第一个使用者为主人
      /setup add <QQ号>      → 主人添加管理员
      /setup remove <QQ号>   → 主人移除管理员
      /memory <内容>         → 主人/管理员添加核心记忆
      /memory list           → 查看核心记忆列表
      /memory clear          → 主人清除所有核心记忆
    """
    cfg = get_group_config(group_id)

    # ── /setup master：设置主人（仅首次有效） ──
    if raw_text == "/setup master":
        if cfg.get("master") is None:
            cfg["master"] = user_id
            cfg["admins"] = []
            cfg["memories"] = []
            set_group_config(group_id, cfg)
            await send_msg(ws, group_id,
                           f"✅ 你已成为本群的主人喵~ (QQ:{user_id})", "group")
            print(f"[权限] 群{group_id} 主人已设置: {user_id}")
        elif cfg["master"] == user_id:
            await send_msg(ws, group_id, "你已经是主人了喵~ 用 /setup add +QQ号 添加管理员", "group")
        else:
            await send_msg(ws, group_id, "本群已经有主人了，无法重复设置喵~", "group")
        return "handled"

    # ── 以下指令需要验证权限 ──
    is_master = (cfg.get("master") == user_id)
    is_admin = user_id in cfg.get("admins", [])

    if not is_master and not is_admin:
        # 非管理员尝试使用指令
        if raw_text.startswith("/setup") or raw_text.startswith("/memory"):
            if cfg.get("master") is None:
                await send_msg(ws, group_id,
                               "本群还没设置主人，请先发送「/setup master」设置主人喵~", "group")
            else:
                await send_msg(ws, group_id, "只有主人和管理员才能使用管理指令喵~", "group")
            return "handled"
        return None  # 不是指令，交给 AI

    # ── /setup add <QQ号>：添加管理员（仅主人） ──
    if raw_text.startswith("/setup add"):
        if not is_master:
            await send_msg(ws, group_id, "只有主人才能添加管理员喵~", "group")
            return "handled"
        parts = raw_text.split()
        if len(parts) < 3:
            await send_msg(ws, group_id, "格式：/setup add QQ号 喵~", "group")
            return "handled"
        target = parts[2].strip()
        if target not in cfg["admins"]:
            cfg["admins"].append(target)
            set_group_config(group_id, cfg)
            await send_msg(ws, group_id, f"✅ 已添加管理员 (QQ:{target})", "group")
        else:
            await send_msg(ws, group_id, "该用户已经是管理员了喵~", "group")
        return "handled"

    # ── /setup remove <QQ号>：移除管理员（仅主人） ──
    if raw_text.startswith("/setup remove"):
        if not is_master:
            await send_msg(ws, group_id, "只有主人才能移除管理员喵~", "group")
            return "handled"
        parts = raw_text.split()
        if len(parts) < 3:
            await send_msg(ws, group_id, "格式：/setup remove QQ号 喵~", "group")
            return "handled"
        target = parts[2].strip()
        if target in cfg["admins"]:
            cfg["admins"].remove(target)
            set_group_config(group_id, cfg)
            await send_msg(ws, group_id, f"🗑️ 已移除管理员 (QQ:{target})", "group")
        else:
            await send_msg(ws, group_id, "该用户不是管理员喵~", "group")
        return "handled"

    # ── /memory <内容>：添加核心记忆 ──
    if raw_text.startswith("/memory "):
        content = raw_text[len("/memory "):].strip()
        if not content:
            await send_msg(ws, group_id, "格式：/memory 要记住的内容 喵~", "group")
            return "handled"
        if content == "list":
            # 查看记忆列表
            memories = cfg.get("memories", [])
            if not memories:
                await send_msg(ws, group_id, "本群还没有核心记忆喵~", "group")
            else:
                lines = [f"{i+1}. {m}" for i, m in enumerate(memories)]
                await send_msg(ws, group_id, "📝 核心记忆：\n" + "\n".join(lines), "group")
            return "handled"
        if content == "clear":
            if not is_master:
                await send_msg(ws, group_id, "只有主人才能清除核心记忆喵~", "group")
                return "handled"
            cfg["memories"] = []
            set_group_config(group_id, cfg)
            await send_msg(ws, group_id, "🗑️ 所有核心记忆已清除", "group")
            return "handled"
        # 添加记忆
        if "memories" not in cfg:
            cfg["memories"] = []
        cfg["memories"].append({"text": content, "added_by": user_id})
        set_group_config(group_id, cfg)
        await send_msg(ws, group_id, f"✅ 已记住：{content}", "group")
        return "handled"

    # ── /setup info：查看配置 ──
    if raw_text == "/setup info":
        lines = [f"👤 主人: QQ:{cfg.get('master', '未设置')}"]
        admins = cfg.get("admins", [])
        if admins:
            lines.append(f"👥 管理员: {', '.join(f'QQ:{a}' for a in admins)}")
        else:
            lines.append("👥 管理员: 暂无")
        memories = cfg.get("memories", [])
        lines.append(f"📝 核心记忆: {len(memories)} 条")
        await send_msg(ws, group_id, "\n".join(lines), "group")
        return "handled"

    return None  # 未匹配指令，交给 AI


def load_history():
    """从文件加载群聊历史"""
    global group_history
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 只保留最近的记录，兼容旧格式
                if isinstance(data, dict):
                    group_history = data
                    print(f"[历史] 已加载 {sum(len(v) for v in data.values())} 条历史消息")
    except Exception as e:
        print(f"[历史] 加载失败: {e}")


def save_history():
    """保存群聊历史到文件"""
    try:
        # 只保存每个群最近的 N 条
        trimmed = {
            gid: msgs[-MAX_HISTORY_PER_GROUP:]
            for gid, msgs in group_history.items() if msgs
        }
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


async def init_mcp():
    """初始化 MCP 工具和 LLM"""
    global _shared_tools, _llm
    print("[MCP] 正在连接 MCP 服务...")
    client = MultiServerMCPClient({
        "web_mcp": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["mcp_web.py"],
        },
        "time_mcp": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["mcp_time.py"],
        },
        "knowledge_mcp": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["mcp_knowledge.py"],
        },
    })
    _shared_tools = await client.get_tools()
    print(f"[MCP] 工具加载完成: {[t.name for t in _shared_tools]}")

    _llm = ChatOpenAI(
        model=get_model_config()["model"],
        api_key=get_model_config()["api_key"],
        base_url=get_model_config()["base_url"],
        temperature=0.7,
    )
    print(f"[模型] {MODEL_PROVIDER} / {get_model_config()['model']}")


async def get_agent(uid: str):
    """获取或创建用户的 Agent（独立记忆）"""
    if uid not in agent_map:
        memory = MemorySaver()
        config = {"configurable": {"thread_id": uid}}
        agent = create_agent(
            model=_llm,
            tools=_shared_tools,
            system_prompt=build_system_prompt(),
            checkpointer=memory,
        )
        agent_map[uid] = (agent, config)
        print(f"[会话] 新会话: {uid} (性格: {BOT_PERSONALITY})")
    return agent_map[uid]


# ── API 调用辅助（等待 OneBot 返回结果）──
_pending_api: dict[str, asyncio.Future] = {}

async def call_api(ws, action: str, params: dict) -> dict | None:
    """发送 OneBot API 请求并等待响应"""
    echo = f"echo_{id(params)}_{asyncio.get_event_loop().time()}"
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending_api[echo] = fut
    payload = {"action": action, "params": params, "echo": echo}
    await ws.send(json.dumps(payload))
    try:
        return await asyncio.wait_for(fut, timeout=5)
    except asyncio.TimeoutError:
        _pending_api.pop(echo, None)
        return None


async def send_msg(ws, target: str, message: str, msg_type: str = "private"):
    """发送 QQ 消息（私聊/群聊）"""
    payload = {
        "action": "send_msg",
        "params": {"message": message, "message_type": msg_type},
    }
    if msg_type == "private":
        payload["params"]["user_id"] = int(target)
    else:
        payload["params"]["group_id"] = int(target)
    await ws.send(json.dumps(payload))


def is_at_bot(message_segments: list, bot_uin: str) -> bool:
    """检查消息中是否 @了机器人"""
    for seg in message_segments:
        if seg.get("type") == "at" and str(seg.get("data", {}).get("qq", "")) == bot_uin:
            return True
    return False


def extract_text(message_segments: list) -> str:
    """从消息段中提取纯文本，去掉所有 @标记"""
    parts = []
    for seg in message_segments:
        if seg.get("type") == "text":
            parts.append(seg["data"]["text"])
    return "".join(parts).strip()


# ── 群成员昵称缓存 ──
_group_member_cache: dict[tuple[str, str], str] = {}

async def get_group_member_name(ws, group_id: str, user_id: str) -> str:
    """获取群成员昵称（带缓存）"""
    key = (group_id, user_id)
    if key not in _group_member_cache:
        info = await call_api(ws, "get_group_member_info", {
            "group_id": int(group_id),
            "user_id": int(user_id),
        })
        if info and info.get("status") == "ok":
            data = info["data"]
            name = data.get("card") or data.get("nickname") or f"QQ{user_id}"
            _group_member_cache[key] = name
        else:
            _group_member_cache[key] = f"QQ{user_id}"
    return _group_member_cache[key]


# ── 群成员列表缓存 ──
_group_list_cache: dict[str, tuple[list[dict[str, str]], float]] = {}
GROUP_LIST_CACHE_TTL = 300  # 5 分钟刷新一次

async def get_group_member_list(ws, group_id: str) -> list[dict[str, str]]:
    """获取群成员列表（带缓存），返回 [{user_id, name}, ...]"""
    now = asyncio.get_event_loop().time()
    cached = _group_list_cache.get(group_id)
    if cached and (now - cached[1]) < GROUP_LIST_CACHE_TTL:
        return cached[0]

    info = await call_api(ws, "get_group_member_list", {"group_id": int(group_id)})
    members = []
    if info and info.get("status") == "ok":
        data_list = info.get("data", [])
        for m in data_list:
            uid = str(m.get("user_id", ""))
            name = m.get("card") or m.get("nickname") or f"QQ{uid}"
            members.append({"user_id": uid, "name": name})
            # 同时回填昵称缓存
            _group_member_cache[(group_id, uid)] = name
    _group_list_cache[group_id] = (members, now)
    return members


def format_member_list(members: list[dict[str, str]]) -> str:
    """格式化群成员列表为可读字符串"""
    if not members:
        return ""
    names = [m["name"] for m in members]
    # 只展示前 30 人，避免消息过长
    if len(names) > 30:
        return f"群共 {len(members)} 人: {', '.join(names[:30])}...（等）"
    return f"群成员: {', '.join(names)}"


async def build_rich_message(message_segments: list, ws, group_id: str | None, bot_uin: str) -> tuple[str, str]:
    """将消息段转换为带 @上下文的可读文本。
    
    返回: (rich_text（带@上下文给AI看）, clean_text（纯文本用于名字解析）)
    - @自己 → @我
    - @其他人 → @群昵称
    - @所有人 → @所有人
    """
    rich_parts = []
    clean_parts = []
    
    for seg in message_segments:
        if seg.get("type") == "text":
            text = seg["data"]["text"]
            rich_parts.append(text)
            clean_parts.append(text)
        elif seg.get("type") == "at":
            qq = str(seg.get("data", {}).get("qq", ""))
            if qq == bot_uin:
                rich_parts.append("@我")
                # @机器人本身 — 不清除，AI 需要知道是在叫它
            elif qq == "all":
                rich_parts.append("@所有人")
            elif group_id:
                # 异步查群成员昵称
                name = await get_group_member_name(ws, group_id, qq)
                rich_parts.append(f"@{name}")
            else:
                rich_parts.append(f"@QQ{qq}")
    
    rich = "".join(rich_parts).strip()
    clean = "".join(clean_parts).strip()
    return rich, clean


async def handle_msg(ws, data: dict):
    """处理收到的 QQ 消息"""
    global _bot_uin

    if data.get("post_type") != "message":
        return

    # 缓存机器人自己的 QQ 号
    if _bot_uin is None and data.get("self_id"):
        _bot_uin = str(data["self_id"])
        print(f"[Bot] 机器人 QQ: {_bot_uin}")

    msg_type = data.get("message_type", "private")
    user_id = str(data.get("user_id"))
    if not user_id:
        return

    # 群聊处理：检查是否 @了机器人
    if msg_type == "group":
        group_id = str(data.get("group_id", ""))
        message_segments = data.get("message", [])
        raw_text = data.get("raw_message", "").strip()

        # ── 处理群管理指令（不需要 @机器人） ──
        if raw_text.startswith("/"):
            result = await handle_group_command(
                group_id, user_id, raw_text, ws, group_name
            )
            if result == "handled":
                return

        # 无人@ + 没有关键词 → 跳过
        if not is_at_bot(message_segments, _bot_uin or ""):
            if not BOT_NAME or BOT_NAME not in raw_text:
                return

        # 构建带 @上下文的富文本
        rich_text, _ = await build_rich_message(
            message_segments, ws, group_id, _bot_uin or ""
        )

        # 获取发送者的群名片
        sender = data.get("sender", {})
        display_name = sender.get("card") or sender.get("nickname") or f"QQ{user_id}"

        # 获取群名称
        group_info = await call_api(ws, "get_group_info", {"group_id": int(group_id)})
        group_name = "未知群"
        if group_info and group_info.get("status") == "ok":
            group_name = group_info.get("data", {}).get("group_name", str(group_id))

        # 获取群成员列表（缓存）
        members = await get_group_member_list(ws, group_id)
        member_summary = format_member_list(members)

        # 富文本 + 群成员信息一并发给 AI
        display_msg = (
            f"[群:{group_name}](ID:{group_id}) "
            f"{display_name}(QQ:{user_id}) 说: {rich_text}\n"
            f"{member_summary}"
        )

        # ── 附加上下文：最近群聊历史 ──
        session_id = f"group_{group_id}"
        hist = group_history.get(session_id, [])[-MAX_HISTORY_PER_GROUP:]
        if hist:
            history_text = "\n".join(
                f"{m['name']}(QQ:{m.get('uid','?')}): {m['text'][:100]}" for m in hist
            )
            display_msg += f"\n\n【最近群聊】\n{history_text}"

        # ── 附加上下文：核心记忆 ──
        cfg = get_group_config(group_id)
        memories = cfg.get("memories", [])
        if memories:
            mem_text = "\n".join(f"· {m['text']}" if isinstance(m, dict) else f"· {m}" for m in memories)
            display_msg += f"\n\n【核心记忆】\n{mem_text}"

        # ── 保存本消息到历史 ──
        group_history.setdefault(session_id, []).append({
            "name": display_name,
            "uid": user_id,
            "text": rich_text,
            "time": asyncio.get_event_loop().time(),
        })
        # 裁剪历史到最大长度
        if len(group_history[session_id]) > MAX_HISTORY_PER_GROUP * 2:
            group_history[session_id] = group_history[session_id][-MAX_HISTORY_PER_GROUP:]
        # 持久化到文件
        save_history()

        target_id = group_id
        target_type = "group"
    else:
        # 私聊直接处理
        target_id = user_id
        target_type = "private"
        session_id = f"private_{user_id}"
        raw_msg = data.get("raw_message", "").strip()

        # 附加上下文：最近私聊历史
        hist = group_history.get(session_id, [])[-MAX_HISTORY_PER_GROUP:]
        if hist:
            history_text = "\n".join(
                f"{m['name']}(QQ:{m.get('uid','?')}): {m['text'][:100]}" for m in hist
            )
            display_msg = f"{raw_msg}\n\n【最近私聊】\n{history_text}"
        else:
            display_msg = raw_msg

        # ── 保存本消息到历史 ──
        sender = data.get("sender", {})
        display_name = sender.get("nickname") or f"QQ{user_id}"
        group_history.setdefault(session_id, []).append({
            "name": display_name,
            "uid": user_id,
            "text": raw_msg,
            "time": asyncio.get_event_loop().time(),
        })
        if len(group_history[session_id]) > MAX_HISTORY_PER_GROUP * 2:
            group_history[session_id] = group_history[session_id][-MAX_HISTORY_PER_GROUP:]
        save_history()

    if not display_msg:
        return

    print(f"[QQ] ({target_type}) 来自 {user_id}: {display_msg[:80]}")

    try:
        agent, config = await get_agent(session_id)
        # 让 AI 先思考是否需要搜索，再回答
        search_reminder = (
            "\n\n（提示：如果需要搜索信息或查询实时内容，请先使用 search_web 工具，"
            "不要凭自己的知识回答不确定的问题。）"
        )
        res = await agent.ainvoke(
            {"messages": [{"role": "user", "content": display_msg + search_reminder}]},
            config=config,
        )
        reply = res["messages"][-1].content
    except Exception as e:
        print(f"[错误] {e}")
        reply = f"唔…处理的时候出了点小问题：{type(e).__name__}"

    # 分条发送（QQ 单条消息上限约 2000 字）
    for i in range(0, len(reply), 2000):
        chunk = reply[i: i + 2000]
        await send_msg(ws, target_id, chunk, target_type)
    print(f"[QQ] 回复完成 ({len(reply)} 字符)")


async def main():
    # 加载持久化的群聊历史
    load_history()
    print(f"[历史] 群聊历史文件: {HISTORY_FILE}")

    await init_mcp()
    print(f"[WS] 正在连接 {WS_URL} ...")
    async for ws in connect(WS_URL, ping_interval=30):
        print("[WS] 已连接！等待 QQ 消息...")
        print(f"[WS]  私聊 → 自动回复")
        print(f"[WS]  群聊 → @我 或 提及「{BOT_NAME or '未设置'}」触发")
        async for raw in ws:
            try:
                data = json.loads(raw)
                # 检查是不是 API 调用的返回结果
                echo = data.get("echo")
                if echo and echo in _pending_api:
                    fut = _pending_api.pop(echo)
                    if not fut.done():
                        fut.set_result(data)
                    continue
                # 普通消息交给 handler
                asyncio.create_task(handle_msg(ws, data))
            except json.JSONDecodeError:
                continue


if __name__ == "__main__":
    asyncio.run(main())
