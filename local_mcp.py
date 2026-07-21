from mcp.server.fastmcp import FastMCP

mcp = FastMCP("本地文件工具服务")

@mcp.tool()
def read_file(file_name: str) -> str:
    """读取项目目录内的文本文件"""
    try:
        with open(file_name, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as err:
        return f"文件读取失败：{str(err)}"

@mcp.tool()
def list_directory() -> str:
    """列出当前项目文件夹内所有文件"""
    import os
    return str(os.listdir("."))

if __name__ == "__main__":
    mcp.run(transport="stdio")