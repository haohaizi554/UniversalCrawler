"""Formatting helpers."""
#数据格式化
import math

def format_size(size_bytes):
    """Render a byte count as a human-friendly string."""
    if size_bytes == 0:
        return "0 B"
    if size_bytes < 0:
        return "Unknown"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = min(int(math.log(size_bytes, 1024)), len(units) - 1)
    power = math.pow(1024, index)
    size = round(size_bytes / power, 2)
    return f"{size} {units[index]}"
