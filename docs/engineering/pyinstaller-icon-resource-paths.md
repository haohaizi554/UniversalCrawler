# PyInstaller 图标资源路径约束

## 背景

GUI 图标在开发环境通常可以通过 `UI/icon/*.png` 相对路径找到，但 PyInstaller 打包后资源会被放进运行时目录 `_MEIPASS/UI/icon`。如果代码直接用 `Path("UI/icon/x.png").is_file()` 判断资源是否存在，打包后会误判缺失，然后回退到 emoji 或文字占位。

## 规则

- 组件仍可把 `UI/icon/<name>.png` 作为逻辑相对路径传给 Qt 图标加载器。
- 需要判断文件是否真实存在时，必须走 `app.services.icon_registry.resolve_ui_icon_path()`。
- 不要在页面、delegate 或 viewmodel 中直接写 `Path(ui_icon_path(...)).is_file()`。
- WebUI 继续使用 `/ui-icon/<name>` 路由，不和 GUI 文件系统路径混用。

## 本次修复点

日志中心平台筛选下拉框和来源列原先用相对路径判断图标是否存在。打包后相对路径失效，导致平台图标回退为 Unicode。现在图标注册表会按顺序搜索：

1. PyInstaller `_MEIPASS`
2. 项目根目录
3. 当前工作目录

这样开发环境、打包环境和测试环境都走同一套资源解析逻辑。
