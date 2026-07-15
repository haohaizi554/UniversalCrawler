"""转换 Cookie 表示形式，并将字节数格式化为可读单位。"""

from http.cookiejar import CookieJar
from re import compile

def cookie_str_to_dict(cookie_str: str) -> dict:
    """将 Cookie 字符串解析为名称和值的字典。"""
    if not cookie_str:
        return {}
    cookie = {}
    pattern = compile(r"(?P<key>[^=;,]+)=(?P<value>[^;,]+)")
    matches = pattern.finditer(cookie_str)
    for match in matches:
        key = match.group("key").strip()
        value = match.group("value").strip()
        cookie[key] = value
    return cookie

def cookie_str_to_str(cookie_str: str) -> str:
    """移除 Set-Cookie 属性，仅保留可用于请求的键值对。"""
    if not cookie_str:
        return ""
    pattern = compile(r", (?=\D)")
    return "; ".join(cookie.split("; ")[0] for cookie in pattern.split(cookie_str))

def cookie_dict_to_str(cookie_dict: dict | CookieJar) -> str:
    """将 Cookie 字典或 CookieJar 连接为请求头字符串。"""
    if not cookie_dict:
        return ""
    cookie_pairs = [f"{key}={value}" for key, value in cookie_dict.items()]
    return "; ".join(cookie_pairs)

def cookie_jar_to_dict(cookie_jar: CookieJar) -> dict:
    """将 CookieJar 转为名称和值的字典。"""
    return {i.name: i.value for i in cookie_jar}

def format_size(size_in_bytes: int) -> str:
    """以 1024 为进位格式化字节数。"""
    units = ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    index = 0
    while size_in_bytes >= 1024 and index < len(units) - 1:
        size_in_bytes /= 1024
        index += 1
    return f"{size_in_bytes:.2f} {units[index]}"

if __name__ == "__main__":
    print(format_size(0))
