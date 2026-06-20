"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/timer.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/timer.py
from time import time

__all__ = ["run_time"]

def run_time(function):
    
    def inner(self, *args, **kwargs):
        
        start = time()
        result = function(self, *args, **kwargs)
        print(f"{function.__name__}运行耗时: {time() - start}s")
        return result

    return inner