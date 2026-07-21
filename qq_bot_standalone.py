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
    """从消息段中提取纯文本，去掉 @标记"""
    parts = []
    for seg in message_segments:
        if seg.get("type") == "text":
            parts.append(seg["data"]["text"])
        # @ 类型的跳过，不纳入文本
    return "".join(parts).strip()


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
    user_id = data.get("user_id")
    if not user_id:
        return

    # 群聊处理：检查是否 @了机器人
    if msg_type == "group":
        group_id = data.get("group_id")
        message_segments = data.get("message", [])
        raw_text = data.get("raw_message", "").strip()

        # 无人@ + 没有关键词 → 跳过
        if not is_at_bot(message_segments, _bot_uin or ""):
            if not BOT_NAME or BOT_NAME not in raw_text:
                return

        # 去掉 @标记，提取纯文本
        clean_text = extract_text(message_segments)
        if not clean_text.strip():
            return

        # 获取发送者的群名片
        sender = data.get("sender", {})
        sender_name = sender.get("card") or sender.get("nickname") or f"QQ{user_id}"

        # 获取群名称
        group_info = await call_api(ws, "get_group_info", {"group_id": group_id})
        group_name = "未知群"
        if group_info and group_info.get("status") == "ok":
            group_name = group_info.get("data", {}).get("group_name", str(group_id))

        target_id = str(group_id)
        target_type = "group"
        session_id = f"group_{group_id}"
        # 把上下文信息拼进去
        display_msg = f"[群:{group_name}] {sender_name}: {clean_text}"
    else:
        # 私聊直接处理
        target_id = str(user_id)
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
