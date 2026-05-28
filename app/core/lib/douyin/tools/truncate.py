"""抖音底层能力模块，负责 `app/core/lib/douyin/tools/truncate.py` 对应的接口、加密、提取或工具逻辑。"""

# app/core/lib/douyin/tools/truncate.py
from unicodedata import name

def is_chinese_char(char: str) -> bool:
    """执行 `is_chinese_char` 对应的业务逻辑。"""
    return "CJK" in name(char, "")

def truncate_string(s: str, length: int = 64) -> str:
    """执行 `truncate_string` 对应的业务逻辑。"""
    count = 0
    result = ""
    for char in s:
        count += 2 if is_chinese_char(char) else 1
        if count > length:
            break
        result += char
    return result

def trim_string(s: str, length: int = 64) -> str:
    """执行 `trim_string` 对应的业务逻辑。"""
    length = length // 2 - 2
    return f"{s[:length]}...{s[-length:]}" if len(s) > length else s

def beautify_string(s: str, length: int = 64) -> str:
    """执行 `beautify_string` 对应的业务逻辑。"""
    count = 0
    for char in s:
        count += 2 if is_chinese_char(char) else 1
        if count > length:
            break
    else:
        return s
    length //= 2
    start = truncate_string(s, length)
    end = truncate_string(s[::-1], length)[::-1]
    return f"{start}...{end}"
