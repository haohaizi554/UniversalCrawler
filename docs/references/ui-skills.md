# 工业级 UI 参考仓库本地索引

更新时间：2026-07-05

这些资料用于学习 GUI、WebUI、组件化、表格模型、主题系统和工业级交互细节。源码仓库使用浅克隆下载到项目本地临时参考目录，避免污染业务代码和 Git 历史。

本地根目录：

```text
D:\desktop\project\UniversalCrawlerProplus\.codex_tmp\ui-skills
```

## GUI / Qt 参考

| 名称 | 本地路径 | 当前提交 | 说明 |
| --- | --- | --- | --- |
| qt-material | `.codex_tmp/ui-skills/repos/qt-material` | `5a99be3` | PyQt/PySide Material Design 主题参考 |
| PyDracula | `.codex_tmp/ui-skills/repos/PyDracula` | `6701b83` | 现代桌面应用模板。原 `andremucchi/PyDracula` 已不可用，实际下载自 `Wanderson-Magalhaes/Modern_GUI_PyDracula_PySide6_or_PyQt6` |
| PyQt-Fluent-Widgets / QFluentWidgets | `.codex_tmp/ui-skills/repos/PyQt-Fluent-Widgets` | `701c0af` | Windows Fluent 风格组件库；列表中的两个条目对应同一仓库 |
| qt-creator | `.codex_tmp/ui-skills/repos/qt-creator` | `c7bbb796` | Qt Creator 工程架构、窗口管理、插件化和大型 Qt 项目组织方式参考 |
| qtbase | `.codex_tmp/ui-skills/repos/qtbase` | `45c13908` | Qt 官方底层实现参考，重点看 model/view、窗口、样式和平台适配 |
| Kivy | `.codex_tmp/ui-skills/repos/kivy` | `26f870b` | 跨平台 UI 架构参考 |

## WebUI / 后台系统参考

| 名称 | 本地路径 | 当前提交 | 说明 |
| --- | --- | --- | --- |
| Ant Design Pro | `.codex_tmp/ui-skills/repos/ant-design-pro` | `b0fee89` | 企业级后台布局、权限、表格、Dashboard 参考 |
| Ant Design | `.codex_tmp/ui-skills/repos/ant-design` | `85a08c1` | 企业级组件库、设计 token、表单与表格体系 |
| Material UI | `.codex_tmp/ui-skills/repos/material-ui` | `2bcf35ff` | Material Design Web 组件体系 |
| Tauri | `.codex_tmp/ui-skills/repos/tauri` | `1c573a0` | WebUI 桌面化与跨平台桌面壳参考 |
| React Admin | `.codex_tmp/ui-skills/repos/react-admin` | `e1beaa2` | 数据密集型 CRUD 后台与 API 绑定参考 |
| Element Plus | `.codex_tmp/ui-skills/repos/element-plus` | `020a33f` | Vue 企业后台组件体系参考 |

## UI 方法与组件范式

| 名称 | 本地路径 | 当前提交 | 说明 |
| --- | --- | --- | --- |
| shadcn/ui | `.codex_tmp/ui-skills/repos/shadcn-ui` | `d0fae52` | 可组合组件、token 化样式、现代 SaaS UI 范式 |
| Headless UI | `.codex_tmp/ui-skills/repos/headlessui` | `eea57cf` | UI 行为和样式解耦，菜单、弹窗、选择器等交互逻辑参考 |

## 官方文档离线副本

| 名称 | 本地路径 | 说明 |
| --- | --- | --- |
| Qt Model/View Programming | `.codex_tmp/ui-skills/docs/qt-model-view-programming.html` | Qt Model/View 官方文档离线 HTML，表格、列表、delegate 和数据模型重构时优先参考 |

## 更新方式

如需刷新这些参考资料，可在项目根目录执行浅更新：

```powershell
Get-ChildItem .codex_tmp\ui-skills\repos -Directory |
  ForEach-Object {
    git -C $_.FullName fetch --depth 1 origin
    git -C $_.FullName reset --hard FETCH_HEAD
  }
```

这些资料只作为本地参考，不应直接复制成项目依赖。真正落地到 UniversalCrawlerProplus 时，优先抽取工程原则：组件边界、Model/View、增量刷新、主题 token、窗口平台适配和可访问性，而不是照搬视觉皮肤。
