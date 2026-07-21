"""
🤖 AI 智能助手 - 支持多模式对话
================================
模式1: 基础对话 - 纯 DeepSeek 聊天
模式2: 本地工具 - 文件读写 + 目录管理
模式3: 全能模式 - 文件 + 网页抓取 + 网络搜索

用法: python run.py [模式编号]
"""

import os
import sys
import asyncio
import uuid
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver

# ============================================================
# 1. 配置区
# ============================================================
load_dotenv()

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 大模型配置
LLM_CONFIG = {
    "model": "deepseek-chat",
    "api_key": os.getenv("DEEPSEEK_API_KEY"),
    "base_url": "https://api.deepseek.com/v1",
    "temperature": 0.7,
}

# 系统提示词
SYSTEM_PROMPTS = {
    "basic": "你是我的私人AI助手，回答简洁友好。",
    "local": (
        "你拥有文件读写、目录管理等本地文件操作工具。"
        "读取本地文件时用 read_file 工具，列出目录用 list_directory 工具。"
        "清晰完整地回答用户问题。"
    ),
    "full": (
        "你拥有文件读写、目录管理、网页抓取、网络搜索等工具。"
        "读取本地文件时用文件工具（read_file, list_directory 等），"
        "查询网络知识、百科内容时用网络工具（fetch_webpage 抓取网页、search_web 搜索信息），"
        "清晰完整回答用户问题。"
    ),
}


# ============================================================
# 2. 模式1：基础对话（无工具）
# ============================================================
def run_basic_chat():
    """纯 DeepSeek 对话模式"""
    llm = ChatOpenAI(**LLM_CONFIG)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPTS["basic"]),
        ("human", "{user_question}"),
    ])
    chain = prompt | llm

    print("\n" + "=" * 50)
    print("💬 基础对话模式已启动（输入 exit 退出）")
    print("=" * 50)

    while True:
        try:
            question = input("\n你：").strip()
            if not question:
                continue
            if question.lower() in ("exit", "quit", "q"):
                print("👋 再见！")
                break
            res = chain.invoke({"user_question": question})
            print(f"AI：{res.content}")
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 出错了：{e}")


# ============================================================
# 3. 模式2：本地工具模式（文件读写 + 目录管理）
# ============================================================
async def run_local_tools():
    """带本地文件工具的 MCP 模式"""
    llm = ChatOpenAI(**{**LLM_CONFIG, "temperature": 0})

    client = MultiServerMCPClient({
        "local_file_service": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [os.path.join(BASE_DIR, "local_mcp.py")],
        }
    })

    mcp_tools = await client.get_tools()
    print(f"✅ 本地工具加载完成：{[t.name for t in mcp_tools]}")

    memory = MemorySaver()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    agent = create_agent(
        model=llm,
        tools=mcp_tools,
        system_prompt=SYSTEM_PROMPTS["local"],
        checkpointer=memory,
    )

    print(f"\n{'=' * 50}")
    print(f"📁 本地工具模式已启动（会话ID: {thread_id[:8]}...）")
    print("支持：读取文件、列出目录等操作")
    print("输入 exit 退出")
    print("=" * 50)

    while True:
        try:
            user_input = input("\n你：").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("👋 再见！")
                break
            res = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
            )
            print(f"AI：{res['messages'][-1].content}")
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 出错了：{e}")


# ============================================================
# 4. 模式3：全能模式（文件 + 网页 + 搜索）
# ============================================================
async def run_full_mode():
    """带文件工具 + 网络工具的完整 MCP 模式"""
    llm = ChatOpenAI(**{**LLM_CONFIG, "temperature": 0})

    client = MultiServerMCPClient({
        "file_mcp": {
            "transport": "stdio",
            "command": "cmd.exe",
            "args": [
                "/c",
                "npx",
                "-y",
                "@modelcontextprotocol/server-filesystem",
                BASE_DIR,
            ],
        },
        "web_mcp": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [os.path.join(BASE_DIR, "web_mcp.py")],
        },
    })

    mcp_tools = await client.get_tools()
    print(f"✅ 全能工具加载完成：{[t.name for t in mcp_tools]}")

    memory = MemorySaver()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    agent = create_agent(
        model=llm,
        tools=mcp_tools,
        system_prompt=SYSTEM_PROMPTS["full"],
        checkpointer=memory,
    )

    print(f"\n{'=' * 50}")
    print(f"🌐 全能模式已启动（会话ID: {thread_id[:8]}...）")
    print("支持：文件读写、目录管理、网页抓取、网络搜索")
    print("输入 exit 退出")
    print("=" * 50)

    while True:
        try:
            user_input = input("\n你：").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("👋 再见！")
                break
            res = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
            )
            print(f"AI：{res['messages'][-1].content}")
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 出错了：{e}")


# ============================================================
# 5. 模式选择器
# ============================================================
def show_menu():
    """显示启动菜单"""
    print("\n" + "=" * 50)
    print("🤖 AI 智能助手 - 选择运行模式")
    print("=" * 50)
    print("1️⃣  基础对话  - 纯 DeepSeek 聊天（无需额外依赖）")
    print("2️⃣  本地工具  - 文件读写 + 目录管理")
    print("3️⃣  全能模式  - 文件 + 网页抓取 + 网络搜索")
    print("0️⃣  退出")
    print("=" * 50)


def main():
    """主入口"""
    # 如果命令行传入了模式参数，直接使用
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    else:
        show_menu()
        mode = input("请选择模式 (0-3)：").strip()

    if mode == "1":
        run_basic_chat()
    elif mode == "2":
        asyncio.run(run_local_tools())
    elif mode == "3":
        asyncio.run(run_full_mode())
    elif mode in ("0", "exit", "quit"):
        print("👋 再见！")
        sys.exit(0)
    else:
        print("❌ 无效选择，请输入 0-3")
        main()


if __name__ == "__main__":
    main()
