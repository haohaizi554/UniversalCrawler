"""生成秒级时间戳和临时随机字符串。"""

from random import choice
from string import (
    ascii_lowercase,
    ascii_uppercase,
    digits,
)
from time import time

CHARACTER = ascii_lowercase + ascii_uppercase + digits

def timestamp() -> str:
    """返回当前 Unix 时间戳的十位秒级字符串。"""
    return str(time())[:10]

def random_string(length: int = 10) -> str:
    """从 ASCII 大小写字母和数字中生成指定长度的字符串。"""
    return "".join(choice(CHARACTER) for _ in range(length))

if __name__ == "__main__":
    print(timestamp())
    print(random_string())
