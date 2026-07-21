import asyncio
import os
import uuid
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver

# 读取同目录.env密钥文件
load_dotenv()

# DeepSeek大模型初始化
llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    temperature=0
)

async def connect_mcp():
    # 连接MCP服务：文件读写 + 网页抓取
    import sys
    client = MultiServerMCPClient({
        "file_mcp": {
            "transport": "stdio",
            "command": "cmd.exe",
            "args": [
                "/c", "npx",
                "-y",
                "@modelcontextprotocol/server-filesystem",
                "C:\\Users\\nico\\Desktop\\ai-agent"
            ]
        },
        "web_mcp": {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["web_mcp.py"]
        }
    })
    mcp_tools = await client.get_tools()
    print("✅ MCP工具加载完成：", [t.name for t in mcp_tools])

    # 记忆功能 - 使用内存检查点保存对话历史
    memory = MemorySaver()
    # 每个会话生成唯一 thread_id，也可手动指定
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    agent = create_agent(
        model=llm,
        tools=mcp_tools,
        system_prompt="你拥有文件读写、目录管理、网页抓取、网络搜索等工具。读取本地文件时用文件工具（read_file, list_directory 等），查询网络知识、百科内容时用网络工具（fetch_webpage 抓取网页、search_web 搜索信息），清晰完整回答用户问题。",
        checkpointer=memory,
    )

    print(f"\n==== MCP助手启动 (会话ID: {thread_id[:8]}...) 输入exit退出 ====")
    while True:
        user_text = input("\n你的提问：")
        if user_text == "exit":
            break
        res = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_text}]},
            config=config
        )
        print("AI回答：", res["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(connect_mcp())