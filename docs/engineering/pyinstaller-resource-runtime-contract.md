# PyInstaller 资源运行时契约

## 背景

打包后资源通常位于 PyInstaller 的 `_MEIPASS` 目录，开发态的相对路径不一定还能成立。常见表现是：GUI 图标回退成文字或 emoji、WebUI 静态资源 404、QSS 中的勾选图标不显示、外部工具在打包后找不到。

## 约束

- WebUI 静态目录使用 `resolve_resource_file("app/web/static")`。
- WebUI 图标挂载目录使用 `resolve_resource_file("UI/icon")`。
- GUI/QSS 需要读取本地图标时使用 `resolve_ui_icon_path()`。
- Web 页面继续使用 `/ui-icon/<file>` 路由，不直接暴露本地文件路径。
- 外部工具统一使用 `resolve_tool_file()`，包括 `ffmpeg.exe`、`ffprobe.exe`、`N_m3u8DL-RE.exe`。

## 不推荐写法

```python
Path(__file__).parent / "static"
Path(__file__).resolve().parents[2] / "UI" / "icon"
Path("UI/icon/status_success.png").resolve()
```

这些写法在源码目录运行时看起来正常，但打包后会绕过 `_MEIPASS`。

## 推荐写法

```python
from app.utils.runtime_paths import resolve_resource_file
from app.services.icon_registry import resolve_ui_icon_path

STATIC_DIR = resolve_resource_file("app/web/static")
UI_ICON_DIR = resolve_resource_file("UI/icon")
check_icon = resolve_ui_icon_path("status_success.png")
```

## 测试要求

- 图标注册表需要覆盖 `_MEIPASS` 下的图标解析。
- Web server 需要验证 `STATIC_DIR` 和 `UI_ICON_DIR` 来自统一资源解析器。
- QSS 图标不能直接使用当前工作目录下的 `UI/icon/...`。
