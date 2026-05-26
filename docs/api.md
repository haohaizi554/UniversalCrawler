# 内部接口说明

## 配置

- `app.config.cfg`
  - 统一配置入口，实际类型为 `ConfigManager`
  - 当前配置模型为 `common / missav / bilibili / douyin / auth / download / ui`
  - 继续保留 `get / set / save_ui_state / update_missav_proxy` 接口兼容

- `app.models`
  - 导出 `VideoItem`

- `app.utils`
  - 导出 `sanitize_filename / format_size` 以及兼容配置导出

## 下载器

- `app.core.downloaders`
  - 导出所有下载器与公共基类

- `app.core.downloaders.external`
  - 统一管理 `ffmpeg / N_m3u8DL-RE` 的工具发现、命令构建和执行辅助能力

## 插件注册

- `app.core.plugin_registry.registry`
  - 主插件注册入口

- `app.core.plugins.registry`
  - 实际插件注册实现
  - `PluginRegistry` 与默认 `registry` 对象定义于此

## 服务层

- `MediaLibraryService.scan_directory(directory)`
  - 扫描本地媒体文件

- `DebugArtifactsService.open_latest_log()`
  - 打开最新调试日志

- `DebugArtifactsService.open_latest_error_summary()`
  - 打开最近错误摘要

- `DebugArtifactsService.copy_trace_id(clipboard, trace_id)`
  - 把当前任务的 `trace_id` 复制到剪贴板

## UI

- `app.ui.dialogs.SelectionDialog`
  - 下载前的任务选择弹窗

- `app.ui.styles.generate_stylesheet(is_dark)`
  - 生成深浅色主题样式

- `app.ui.widgets.ClickableVideoWidget`
  - 支持双击全屏切换的视频控件
