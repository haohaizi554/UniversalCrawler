"""抖音底层能力模块，负责 `app/core/lib/douyin/interface/detail.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/interface/detail.py
from typing import Callable
from typing import TYPE_CHECKING
from typing import Union

from .template import API
from app.config import DEFAULT_USER_AGENT

try:
    from ..translation import _
except ImportError:
    def _(x):
        """提供 `_` 对应的内部辅助逻辑。"""
        return x

if TYPE_CHECKING:
    from typing import Any

    Parameter = Any
    Params = Any


class Detail(API):
    """封装 `Detail` 在 `app/core/lib/douyin/interface/detail.py` 中承担的核心逻辑。"""
    def __init__(
            self,
            params: Union["Parameter", "Params"],
            cookie: str = "",
            proxy: str = None,
            detail_id: str = ...,
    ):
        """初始化当前实例并准备运行所需的状态，供 `Detail` 使用。"""
        super().__init__(params, cookie, proxy)
        self.detail_id = detail_id
        self.api = f"{self.domain}aweme/v1/web/aweme/detail/"
        self.text = _("作品")

    def generate_params(
            self,
    ) -> dict:
        """执行 `generate_params` 对应的业务逻辑，供 `Detail` 使用。"""
        return self.params | {
            "aweme_id": self.detail_id,
            "version_code": "190500",
            "version_name": "19.5.0",
        }

    async def run(
            self,
            referer: str = None,
            single_page=True,
            data_key: str = "aweme_detail",
            error_text="",
            cursor="cursor",
            has_more="has_more",
            params: Callable = lambda: {},
            data: Callable = lambda: {},
            method="GET",
            headers: dict = None,
            *args,
            **kwargs,
    ):
        """执行当前对象或脚本的主流程，供 `Detail` 使用。"""
        return await super().run(
            referer,
            single_page,
            data_key,
            error_text,
            cursor,
            has_more,
            params,
            data,
            method,
            headers,
            *args,
            **kwargs,
        )

    def check_response(
            self,
            data_dict: dict,
            data_key: str,
            error_text="",
            cursor="cursor",
            has_more="has_more",
            *args,
            **kwargs,
    ):
        """执行 `check_response` 对应的业务逻辑，供 `Detail` 使用。"""
        try:
            if not (d := data_dict[data_key]):
                self.log.warning(error_text)
            else:
                self.response = d
        except KeyError:
            self.log.error(
                _("数据解析失败，请告知作者处理: {data}").format(data=data_dict)
            )


async def test():
    # 模拟 Params 类
    """执行 `test` 对应的业务逻辑。"""
    class MockParams:
        """封装 `MockParams` 在 `app/core/lib/douyin/interface/detail.py` 中承担的核心逻辑。"""
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        max_retry = 3
        timeout = 10
        logger = None
        ab = None
        console = None
        client = None  # 需要 mock 一个 client

    # 这里的 test 代码很难独立运行，因为它依赖 tools/parameter.py 和 tools/session.py 的完整初始化
    # 所以我们暂时注释掉具体的执行部分，只保留类定义检查
    pass


if __name__ == "__main__":
    from asyncio import run

    run(test())
