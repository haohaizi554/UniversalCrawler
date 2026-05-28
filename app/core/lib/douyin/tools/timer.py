"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/timer.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/timer.py
from time import time

__all__ = ["run_time"]


def run_time(function):
    """执行 `run_time` 对应的业务逻辑。"""
    def inner(self, *args, **kwargs):
        """执行 `inner` 对应的业务逻辑。"""
        start = time()
        result = function(self, *args, **kwargs)
        print(f"{function.__name__}运行耗时: {time() - start}s")
        return result

    return inner