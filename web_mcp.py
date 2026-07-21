"""本地网络工具 MCP 服务 - 支持网页抓取、百科查询"""
from mcp.server.fastmcp import FastMCP
import httpx
from html.parser import HTMLParser
import urllib.parse
import json

mcp = FastMCP("本地网络工具服务")

# 完整浏览器请求头，绕过反爬
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
}


class TextExtractor(HTMLParser):
    """提取 HTML 中的所有文本内容"""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)

    def get_text(self) -> str:
        return "\n".join(self.text_parts)


def extract_text(html: str, max_length: int = 8000) -> str:
    """从 HTML 提取纯文本"""
    parser = TextExtractor()
    parser.feed(html)
    text = parser.get_text()
    lines = [line for line in text.split("\n") if line.strip()]
    result = "\n".join(lines)
    if len(result) > max_length:
        result = result[:max_length] + "\n\n...（内容过长，已截断）"
    return result


def http_get(url: str, timeout: int = 20) -> httpx.Response:
    """发送 HTTP GET 请求，带完整浏览器头"""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        return client.get(url, headers=BROWSER_HEADERS)


@mcp.tool()
def fetch_webpage(url: str) -> str:
    """获取任意网页的文本内容，适合阅读文章、新闻等"""
    try:
        resp = http_get(url)
        resp.raise_for_status()
        text = extract_text(resp.text)
        return f"URL: {url}\n\n{text}"
    except Exception as e:
        return f"抓取失败：{str(e)}"


@mcp.tool()
def search_web(keyword: str) -> str:
    """搜索网络信息（新闻、百科、知识等），返回简洁结果摘要"""
    try:
        encoded = urllib.parse.quote(keyword)
        # 同时搜百度 + 百度百科，取更丰富的结果
        results = []

        # 百度搜索
        try:
            url = f"https://www.baidu.com/s?wd={encoded}&rn=5"
            resp = http_get(url)
            text = extract_text(resp.text, max_length=3000)
            if text:
                results.append(f"【网络搜索结果】\n{text}")
        except Exception:
            pass

        # 百度百科
        try:
            url = f"https://baike.baidu.com/item/{encoded}"
            resp = http_get(url, timeout=10)
            if resp.status_code == 200:
                text = extract_text(resp.text, max_length=4000)
                if text:
                    results.append(f"【百度百科】\n{text}")
        except Exception:
            pass

        if not results:
            return f"没搜到关于「{keyword}」的信息喵~ 换换关键词试试？"

        return "\n\n---\n\n".join(results)
    except Exception as e:
        return f"搜索的时候出了点问题喵：{str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
