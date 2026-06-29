"""抖音底层能力模块，负责 `app/core/lib/douyin/link/requester.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/link/requester.py
from re import compile
from typing import TYPE_CHECKING

# 调整引用路径
try:
    from ..tools import (
        TIMEOUT,
        DownloaderError,
        Retry,
        capture_error_request,
        wait,
    )
except ImportError:
    # 简单的 Mock 防止导入错误
    TIMEOUT = 10

    class DownloaderError(Exception):
        """定义 `DownloaderError` 异常类型，用于表达特定失败场景。"""
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
    # [FIX] 修正 Parameter 导入路径
    from ..tools.parameter import Parameter

__all__ = ["Requester"]

class Requester:
    
    URL = compile(r"(https?://[^\s\"<>\\^`{|}，。；！？、【】《》]+)")

    def __init__(
            self,
            params: "Parameter",
            client: "AsyncClient",
            headers: dict[str, str],
    ):
        """初始化当前实例并准备运行所需的状态，供 `Requester` 使用。"""
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
        """执行当前对象或脚本的主流程，供 `Requester` 使用。"""
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
        # 简单判断是否需要处理（抖音短链通常是 v.douyin.com）
        if "douyin.com" not in url and "tiktok.com" not in url:
            # 如果不是目标域名，直接返回原链接，避免无效请求
            return url

        match (content in {"url", "headers"}, bool(proxy)):
            # 这里简化逻辑，统一使用 client 的异步方法
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
