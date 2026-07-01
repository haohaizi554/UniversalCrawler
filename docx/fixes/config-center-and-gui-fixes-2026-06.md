# 配置中心与 GUI 修复总览（2026-06）

## 背景

2026-06 期间，配置中心和 GUI 暴露出一组相关问题：设置项没有完全热加载、GUI 与 WebUI 默认值不一致、下拉框弹层尺寸和主题不稳定、主题/语言切换存在白屏式重绘、代理设置没有做到选择与输入并存，以及默认打开方式弹窗只显示但没有真正落地。

这些问题的共同根因是：可见控件、运行时配置和前端快照之间没有完全收敛到同一份契约。修复目标不是单独调一个控件，而是让 GUI、WebUI 和后端配置对同一设置项给出一致解释。

## 已合并的修复主题

- 配置中心选项化和热加载：设置选项从后端快照读取，避免 GUI 固定写死默认值。
- 零值回退：数值设置允许 `0` 作为有效值，不能被错误当成空值回退。
- 平台代理启用状态：修复平台代理启用字段类型不一致导致的控件状态漂移。
- 主题闪屏和入口崩溃：主题切换时批量应用样式和调色板，降低白屏和异常退出概率。
- 主题同步与代理契约：保证顶部入口、设置页和 WebUI 使用同一主题/代理状态。
- 下拉框与语言目录：统一下拉弹层组件，语言切换覆盖更多可见页面。
- 智能换行与底栏布局：避免长文件名、路径和说明文本把底部栏顶出屏幕。
- 弹窗主题与默认打开方式：弹窗控件跟随主题，并明确 Windows 默认打开方式注册流程。
- 仅下载视频开关：确保“跳过封面和图片资源”在任务构建与下载执行链路中都生效。

## 工程结论

- 设置项必须以后端配置快照为事实来源，GUI 控件不能私自维护默认值。
- 下拉框必须使用统一弹层组件，不能依赖平台原生弹层的默认样式。
- 主题、语言、字体和缩放变化要走批处理路径，避免整页重建造成闪屏。
- 代理入口应支持预设选择和自定义输入并存，最终写入统一配置字段。
- Windows 默认打开方式属于系统集成功能，需要明确注册结果和生效时机。
- 修复用户可见设置问题时，应同时检查 GUI、WebUI、配置快照、测试和文档。

## 原始记录

- [details/config-center-options-hotload.md](details/config-center-options-hotload.md)
- [details/config-center-zero-value-hotload.md](details/config-center-zero-value-hotload.md)
- [details/config-center-platform-proxy-enabled-type.md](details/config-center-platform-proxy-enabled-type.md)
- [details/config-center-theme-flash-and-entry-crash.md](details/config-center-theme-flash-and-entry-crash.md)
- [details/config-center-theme-sync-and-proxy-contract.md](details/config-center-theme-sync-and-proxy-contract.md)
- [details/config-center-combo-and-language-20260629.md](details/config-center-combo-and-language-20260629.md)
- [details/runtime-hotload-debug-proxy.md](details/runtime-hotload-debug-proxy.md)
- [details/gui-smart-wrap-bottom-bar-20260629.md](details/gui-smart-wrap-bottom-bar-20260629.md)
- [details/gui-dialog-theme-file-association-20260629.md](details/gui-dialog-theme-file-association-20260629.md)
- [details/video-only-toggle-no-effect-20260630.md](details/video-only-toggle-no-effect-20260630.md)
