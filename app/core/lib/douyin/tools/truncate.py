"""按中英文显示宽度截断或省略长文本。"""

from unicodedata import name

def is_chinese_char(char: str) -> bool:
    """判断字符的 Unicode 名称是否属于 CJK。"""
    return "CJK" in name(char, "")

def truncate_string(s: str, length: int = 64) -> str:
    """按中文双宽、其他字符单宽截取字符串前缀。"""
    count = 0
    result = ""
    for char in s:
        count += 2 if is_chinese_char(char) else 1
        if count > length:
            break
        result += char
    return result

def trim_string(s: str, length: int = 64) -> str:
    """按字符数保留首尾并在中间插入省略号。"""
    length = length // 2 - 2
    return f"{s[:length]}...{s[-length:]}" if len(s) > length else s

def beautify_string(s: str, length: int = 64) -> str:
    """按显示宽度保留首尾，未超限时返回原字符串。"""
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
