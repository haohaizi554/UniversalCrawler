"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/session.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/session.py
from typing import TYPE_CHECKING, Union, Any
from httpx import AsyncClient, AsyncHTTPTransport, Client, HTTPTransport

# 调整引用路径：常量现在位于当前包的 __init__.py 中
try:
    from . import TIMEOUT, USERAGENT
except ImportError:
    from app.config import DEFAULT_USER_AGENT

    TIMEOUT = 10
    USERAGENT = DEFAULT_USER_AGENT

from .error import DownloaderError
from .capture import capture_error_params
from .retry import Retry

if TYPE_CHECKING:
    # 占位符，防止静态类型检查报错
    BaseLogger = Any
    LoggerManager = Any
    Logger = Any

__all__ = ["request_params", "create_client"]

def create_client(
    user_agent=USERAGENT,
    timeout=TIMEOUT,
    headers: dict = None,
    proxy: str = None,
    *args,
    **kwargs,
) -> AsyncClient:
    """创建 `client` 对应的对象、资源或结构。"""
    verify = kwargs.pop("verify", True)
    trust_env = kwargs.pop("trust_env", False)
    client_kwargs = {
        "headers": headers
        or {
            "User-Agent": user_agent,
        },
        "timeout": timeout,
        "follow_redirects": True,
        "verify": verify,
        "trust_env": trust_env,
    }
    if proxy:
        client_kwargs["mounts"] = {
            "http://": AsyncHTTPTransport(proxy=proxy),
            "https://": AsyncHTTPTransport(proxy=proxy),
        }
    return AsyncClient(
        *args,
        **client_kwargs,
        **kwargs,
    )

async def request_params(
    logger: Union[
        "BaseLogger",
        "LoggerManager",
        "Logger",
    ],
    url: str,
    method: str = "POST",
    params: dict | str = None,
    data: dict | str = None,
    useragent=USERAGENT,
    timeout=TIMEOUT,
    headers: dict = None,
    resp="headers",
    proxy: str = None,
    **kwargs,
):
    
    verify = kwargs.pop("verify", True)
    trust_env = kwargs.pop("trust_env", False)
    client_kwargs = {
        "headers": headers
        or {
            "User-Agent": useragent,
            "Content-Type": "application/json; charset=utf-8",
            # "Referer": "https://www.douyin.com/"
        },
        "follow_redirects": True,
        "timeout": timeout,
        "verify": verify,
        "trust_env": trust_env,
    }
    if proxy:
        client_kwargs["mounts"] = {
            "http://": HTTPTransport(proxy=proxy),
            "https://": HTTPTransport(proxy=proxy),
        }
    with Client(
        **client_kwargs,
    ) as client:
        return await request(
            logger,
            client,
            method,
            url,
            resp,
            params=params,
            data=data,
            **kwargs,
        )

@Retry.retry_lite
@capture_error_params
async def request(
    logger: Union[
        "BaseLogger",
        "LoggerManager",
        "Logger",
    ],
    client: Client,
    method: str,
    url: str,
    resp="json",
    **kwargs,
):
    
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    match resp:
        case "headers":
            return response.headers
        case "text":
            return response.text
        case "content":
            return response.content
        case "json":
            return response.json()
        case "url":
            return str(response.url)
        case "response":
            return response
        case _:
            raise DownloaderError
