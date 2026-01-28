from contextlib import suppress
from pathlib import Path


def file_switch(path: Path) -> None:
    if path.exists():
        path.unlink()
    else:
        path.touch()


def remove_empty_directories(path: Path) -> None:
    exclude = {
        "\\.",
        "\\_",
        "\\__",
    }
    # Path.walk 是 Python 3.12 新增的 API。
    # 我们的项目 pyproject.toml 声明 requires-python = ">=3.12,<3.13"，所以这里可以直接使用。
    # 如果后续要兼容低版本，需要改用 os.walk。
    for dir_path, dir_names, file_names in path.walk(
        top_down=False,
    ):
        if any(i in str(dir_path) for i in exclude):
            continue
        if not dir_names and not file_names:
            with suppress(OSError):
                dir_path.rmdir()