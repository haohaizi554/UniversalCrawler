"""提供面向 UI 的数据格式化函数。"""
import math

def format_size(size_bytes):
    """把字节数格式化为便于阅读的容量文本。"""
    if size_bytes == 0:
        return "0 B"
    if size_bytes < 0:
        return "Unknown"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = min(int(math.log(size_bytes, 1024)), len(units) - 1)
    power = math.pow(1024, index)
    size = round(size_bytes / power, 2)
    return f"{size} {units[index]}"
