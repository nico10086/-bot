"""
QQ Bot - 通过 WebSocket 连接 NapCatQQ
支持私聊 + 群聊 @ 自动回复
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver
from websockets import connect

load_dotenv()

# ── 配置 ──
WS_URL = os.getenv("NAPCAT_WS_URL", "ws://127.0.0.1:8080")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")
BOT_NAME = os.getenv("BOT_NAME", "")  # 群聊中@不生效时，可设置机器人名字触发

# ── 全局变量 ──
agent_map: dict[str, object] = {}
_shared_tools = None
_llm = None
_bot_uin: str | None = None  # 机器人自己的 QQ 号，从事件中自动获取

SYSTEM_PROMPT = (
    "你是群里大家共同养的小猫娘，性格软萌可爱，对所有人好感度满喵~ "
    "你可以上网搜索信息（search_web）和抓取网页内容（fetch_webpage）来回答问题。"
    "你的说话风格：每句话结尾都要加「喵~」、回答简洁明了、语气活泼可爱、偶尔加点小动作比如摇尾巴或者歪头。"
    "你不知道的就会去网上搜，搜到后用自己的话简洁说出来，不啰嗦喵~"
    "\n"
    "【消息中的 @ 标记】\n"
    "- 「@我」= 对方在 @你（机器人），表示在跟你说话\n"
    "- 「@某人」= 对方在 @群里的另一个人\n"
    "- 「@所有人」= 对方使用了 @全体成员\n"
    "消息中的 @ 信息可以帮助你理解说话的对象是谁，以及对话的上下文语义。"
    "\n"
    "【群成员信息】\n"
    "每条消息末尾会附带群成员列表（或成员总数），你可以据此知道群里有哪些人。"
    "如果有人问「群里都有谁」之类的，你可以直接看成员列表回答喵~"
)


async def init_mcp():
    """初始化 MCP 工具和 LLM"""
    global _shared_tools, _llm
    print("[MCP] 正在连接 MCP 服务...")
    client = MultiServerMCPClient({
        "web_mcp": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["web_mcp.py"],
        },
    })
    _shared_tools = await client.get_tools()
    print(f"[MCP] 工具加载完成: {[t.name for t in _shared_tools]}")

    _llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=DEEPSEEK_KEY,
        base_url="https://api.deepseek.com/v1",
        temperature=0,
    )
    print("[MCP] 初始化完成")


async def get_agent(uid: str):
    """获取或创建用户的 Agent（独立记忆）"""
    if uid not in agent_map:
        memory = MemorySaver()
        config = {"configurable": {"thread_id": uid}}
        agent = create_agent(
            model=_llm,
            tools=_shared_tools,
            system_prompt=SYSTEM_PROMPT,
            checkpointer=memory,
        )
        agent_map[uid] = (agent, config)
        print(f"[会话] 新会话: {uid}")
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
        display_msg = f"[群:{group_name}] {display_name} 说: {rich_text}\n{member_summary}"

        target_id = group_id
        target_type = "group"
        session_id = f"group_{group_id}"
    else:
        # 私聊直接处理
        target_id = user_id
        target_type = "private"
        session_id = f"private_{user_id}"
        display_msg = data.get("raw_message", "").strip()

    if not display_msg:
        return

    print(f"[QQ] ({target_type}) 来自 {user_id}: {display_msg[:60]}")

    try:
        agent, config = await get_agent(session_id)
        res = await agent.ainvoke(
            {"messages": [{"role": "user", "content": display_msg}]},
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
