"""按网页端格式生成 verifyFp 标识。"""

from random import random
from string import ascii_lowercase
from string import ascii_uppercase
from string import digits
from time import time

from rich import print

__all__ = [
    "VerifyFp",
]

class VerifyFp:
    """复现网页端 verifyFp 的时间戳前缀与随机字符布局。"""

    @staticmethod
    def get_verify_fp(timestamp: int = None):
        """生成带 base36 毫秒时间戳和 36 位随机段的 verifyFp。"""
        base_str = digits + ascii_uppercase + ascii_lowercase
        t = len(base_str)
        milliseconds = timestamp or int(round(time() * 1000))
        base36 = ""

        # 时间戳采用网页端 Date.now().toString(36) 的表示方式。
        while milliseconds > 0:
            milliseconds, remainder = divmod(milliseconds, 36)
            if remainder < 10:
                base36 = str(remainder) + base36
            else:
                base36 = chr(ord("a") + remainder - 10) + base36
        # 下划线、版本位和第 19 位掩码必须与网页端格式一致。
        o = [""] * 36
        o[8] = o[13] = o[18] = o[23] = "_"
        o[14] = "4"
        for i in range(36):
            if not o[i]:
                n = int(random() * t)
                if i == 19:
                    n = 3 & n | 8
                o[i] = base_str[n]
        return f"verify_{base36}_" + "".join(o)

if __name__ == "__main__":
    params = 1710413848097
    print(VerifyFp.get_verify_fp(params))
