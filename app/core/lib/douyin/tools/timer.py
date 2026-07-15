"""为同步实例方法输出运行耗时。"""

from time import time

__all__ = ["run_time"]

def run_time(function):
    """包装同步方法，在返回结果前打印秒级耗时。"""
    def inner(self, *args, **kwargs):
        start = time()
        result = function(self, *args, **kwargs)
        print(f"{function.__name__}运行耗时: {time() - start}s")
        return result

    return inner
