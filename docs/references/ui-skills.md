# 工业级 UI 参考仓库索引

更新时间：2026-07-18

这些资料用于学习 GUI、WebUI、组件化、表格模型、主题系统和工业级交互细节。仓库本身不纳入本项目依赖；落地时优先抽取工程原则（组件边界、Model/View、增量刷新、主题 token、窗口平台适配和可访问性），而不是照搬视觉皮肤。

可选本地缓存目录（已在 `.gitignore` 中忽略，需自行浅克隆）：

```text
.codex_tmp/ui-skills/repos/<repo-name>
```

## GUI / Qt 参考

| 名称 | 上游仓库 | 参考提交 | 说明 |
| --- | --- | --- | --- |
| qt-material | [UN-GCPDS/qt-material](https://github.com/UN-GCPDS/qt-material) | `5a99be3` | PyQt/PySide Material Design 主题参考 |
| PyDracula | [Wanderson-Magalhaes/Modern_GUI_PyDracula_PySide6_or_PyQt6](https://github.com/Wanderson-Magalhaes/Modern_GUI_PyDracula_PySide6_or_PyQt6) | `6701b83` | 现代桌面应用模板。原 `andremucchi/PyDracula` 已不可用 |
| PyQt-Fluent-Widgets / QFluentWidgets | [zhiyiYo/PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) | `701c0af` | Windows Fluent 风格组件库 |
| qt-creator | [qt-creator/qt-creator](https://github.com/qt-creator/qt-creator) | `c7bbb796` | Qt Creator 工程架构、窗口管理、插件化和大型 Qt 项目组织方式参考 |
| qtbase | [qt/qtbase](https://github.com/qt/qtbase) | `45c13908` | Qt 官方底层实现参考，重点看 model/view、窗口、样式和平台适配 |
| Kivy | [kivy/kivy](https://github.com/kivy/kivy) | `26f870b` | 跨平台 UI 架构参考 |

## WebUI / 后台系统参考

| 名称 | 上游仓库 | 参考提交 | 说明 |
| --- | --- | --- | --- |
| Ant Design Pro | [ant-design/ant-design-pro](https://github.com/ant-design/ant-design-pro) | `b0fee89` | 企业级后台布局、权限、表格、Dashboard 参考 |
| Ant Design | [ant-design/ant-design](https://github.com/ant-design/ant-design) | `85a08c1` | 企业级组件库、设计 token、表单与表格体系 |
| Material UI | [mui/material-ui](https://github.com/mui/material-ui) | `2bcf35ff` | Material Design Web 组件体系 |
| Tauri | [tauri-apps/tauri](https://github.com/tauri-apps/tauri) | `1c573a0` | WebUI 桌面化与跨平台桌面壳参考 |
| React Admin | [marmelab/react-admin](https://github.com/marmelab/react-admin) | `e1beaa2` | 数据密集型 CRUD 后台与 API 绑定参考 |
| Element Plus | [element-plus/element-plus](https://github.com/element-plus/element-plus) | `020a33f` | Vue 企业后台组件体系参考 |

## UI 方法与组件范式

| 名称 | 上游仓库 | 参考提交 | 说明 |
| --- | --- | --- | --- |
| shadcn/ui | [shadcn-ui/ui](https://github.com/shadcn-ui/ui) | `d0fae52` | 可组合组件、token 化样式、现代 SaaS UI 范式 |
| Headless UI | [tailwindlabs/headlessui](https://github.com/tailwindlabs/headlessui) | `eea57cf` | UI 行为和样式解耦，菜单、弹窗、选择器等交互逻辑参考 |

## 官方文档

| 名称 | 文档 | 说明 |
| --- | --- | --- |
| Qt Model/View Programming | [doc.qt.io Model/View](https://doc.qt.io/qt-6/model-view-programming.html) | 表格、列表、delegate 和数据模型重构时优先参考 |

## 可选本地浅克隆

如需离线翻源码，可在项目根目录自行缓存（不会进入 Git）：

```powershell
$root = ".codex_tmp\ui-skills\repos"
New-Item -ItemType Directory -Force -Path $root | Out-Null
@(
  @{ name = "qt-material"; url = "https://github.com/UN-GCPDS/qt-material.git" },
  @{ name = "PyDracula"; url = "https://github.com/Wanderson-Magalhaes/Modern_GUI_PyDracula_PySide6_or_PyQt6.git" },
  @{ name = "PyQt-Fluent-Widgets"; url = "https://github.com/zhiyiYo/PyQt-Fluent-Widgets.git" },
  @{ name = "qt-creator"; url = "https://github.com/qt-creator/qt-creator.git" },
  @{ name = "qtbase"; url = "https://github.com/qt/qtbase.git" },
  @{ name = "kivy"; url = "https://github.com/kivy/kivy.git" },
  @{ name = "ant-design-pro"; url = "https://github.com/ant-design/ant-design-pro.git" },
  @{ name = "ant-design"; url = "https://github.com/ant-design/ant-design.git" },
  @{ name = "material-ui"; url = "https://github.com/mui/material-ui.git" },
  @{ name = "tauri"; url = "https://github.com/tauri-apps/tauri.git" },
  @{ name = "react-admin"; url = "https://github.com/marmelab/react-admin.git" },
  @{ name = "element-plus"; url = "https://github.com/element-plus/element-plus.git" },
  @{ name = "shadcn-ui"; url = "https://github.com/shadcn-ui/ui.git" },
  @{ name = "headlessui"; url = "https://github.com/tailwindlabs/headlessui.git" }
) | ForEach-Object {
  $dest = Join-Path $root $_.name
  if (-not (Test-Path $dest)) {
    git clone --depth 1 $_.url $dest
  }
}
```

刷新已有缓存：

```powershell
Get-ChildItem .codex_tmp\ui-skills\repos -Directory |
  ForEach-Object {
    git -C $_.FullName fetch --depth 1 origin
    git -C $_.FullName reset --hard FETCH_HEAD
  }
```
