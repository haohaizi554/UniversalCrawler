"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/temporary.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/temporary.py
from random import choice
from string import (
    ascii_lowercase,
    ascii_uppercase,
    digits,
)
from time import time

CHARACTER = ascii_lowercase + ascii_uppercase + digits

def timestamp() -> str:
    
    return str(time())[:10]

def random_string(length: int = 10) -> str:
    
    return "".join(choice(CHARACTER) for _ in range(length))

if __name__ == "__main__":
    print(timestamp())
    print(random_string())