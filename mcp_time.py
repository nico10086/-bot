"""
⏰ 时间工具 MCP 服务 - 获取本地日期时间
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("本地时间工具服务")


@mcp.tool()
def get_local_time() -> str:
    """
    获取本地电脑的当前日期和时间，包含时区信息。
    Bot 可以用这个知道现在是几点、星期几、什么日期。
    """
    import datetime
    now = datetime.datetime.now()
    tz = datetime.datetime.now().astimezone().tzname()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays[now.weekday()]
    return (
        f"📅 本地时间：{now.year}年{now.month:02d}月{now.day:02d}日 "
        f"{weekday} "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}\n"
        f"🕐 时区：{tz}"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
