"""展开抖音和 TikTok 文本中的短链，并按需读取响应内容。"""

from re import compile
from typing import TYPE_CHECKING

try:
    from ..tools import (
        TIMEOUT,
        DownloaderError,
        Retry,
        capture_error_request,
        wait,
    )
except ImportError:
    # 独立加载该文件时保留最小兼容层，避免工具包导入失败阻断链接解析。
    TIMEOUT = 10

    class DownloaderError(Exception):
        """表示链接响应类型不在调用方支持范围内。"""
        pass

    class Retry:
        """提供最小化的重试装饰器兼容层。"""

        @staticmethod
        def retry(func):
            """在兜底模式下直接返回原函数，避免兼容层再引入副作用。"""
            return func

    def capture_error_request(func):
        return func

    async def wait():
        pass

if TYPE_CHECKING:
    from httpx import AsyncClient, get, head
    from ..tools.parameter import Parameter

__all__ = ["Requester"]

class Requester:
    """识别文本 URL，并通过异步客户端跟随目标平台的重定向。"""

    URL = compile(r"(https?://[^\s\"<>\\^`{|}，。；！？、【】《》]+)")

    def __init__(
            self,
            params: "Parameter",
            client: "AsyncClient",
            headers: dict[str, str],
    ):
        """复用调用方提供的客户端、日志器和重试配置。"""
        self.client = client
        self.headers = headers
        self.log = params.logger
        self.max_retry = params.max_retry
        self.timeout = params.timeout

    async def aclose(self) -> None:
        close = getattr(self.client, "aclose", None)
        if callable(close):
            await close()

    async def run(
            self,
            text: str,
            proxy: str = None,
    ) -> str:
        """逐个展开文本 URL，并以空格连接有效结果。"""
        urls = self.URL.finditer(text)
        if not urls:
            return ""
        result = []
        for i in urls:
            result.append(
                await self.request_url(
                    u := i.group(),
                    proxy=proxy,
                )
                or u
            )
            await wait()
        return " ".join(i for i in result if i)

    @Retry.retry
    @capture_error_request
    async def request_url(
            self,
            url: str,
            content="url",
            proxy: str = None,
    ):
        self.log.info(f"URL: {url}", False)
        # 非目标域名原样返回，避免链接解析器向任意站点发起请求。
        if "douyin.com" not in url and "tiktok.com" not in url:
            return url

        match (content in {"url", "headers"}, bool(proxy)):
            case _:
                response = await self.client.get(url, follow_redirects=True)

        self.log.info(f"Response URL: {response.url}", False)
        self.log.info(f"Response Code: {response.status_code}", False)
        self.log.info(f"Response Headers: {dict(response.headers)}", False)

        match content:
            case "text":
                return response.text
            case "content":
                return response.content
            case "json":
                return response.json()
            case "headers":
                return response.headers
            case "url":
                return str(response.url)
            case _:
                raise DownloaderError
