"""切换标记文件状态，并清理不含文件的空目录。"""

from contextlib import suppress
from pathlib import Path

def file_switch(path: Path) -> None:
    """存在时删除标记文件，不存在时创建。"""
    if path.exists():
        path.unlink()
    else:
        path.touch()

def remove_empty_directories(path: Path) -> None:
    """自底向上删除空目录，并跳过隐藏目录和下划线目录。"""
    exclude = {
        "\\.",
        "\\_",
        "\\__",
    }
    # 项目要求 Python 3.12；若降低版本下限，此处需改用 os.walk。
    for dir_path, dir_names, file_names in path.walk(
        top_down=False,
    ):
        if any(i in str(dir_path) for i in exclude):
            continue
        if not dir_names and not file_names:
            with suppress(OSError):
                dir_path.rmdir()
