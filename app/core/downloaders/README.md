# Downloader 模块说明

`app/core/downloaders/` 负责把统一的 `VideoItem` 下载到本地，并在必要时调用外部工具。

## 职责划分

- 平台下载器
  - 负责准备请求头、策略选择和平台差异。
- 通用下载器
  - 负责 chunked、ffmpeg、m3u8 等通用下载路径。
- 外部工具封装
  - 统一收口 `ffmpeg` 与 `N_m3u8DL-RE` 参数构建。

## 与 DownloadWorker 的关系

- `DownloadWorker` 负责文件名、目录、扩展名和执行生命周期。
- 具体 downloader 负责真正的下载动作。
- 下载完成后的扩展名修正仍在 worker 层进行。

## 当前分支重点

本分支特别补充了以下测试：

- 保存路径推导
- 扩展名推断
- 重名文件路径处理
- 文件签名识别
- 平台下载器请求头优先级

## 维护建议

- 新增下载策略时，优先补纯逻辑测试。
- 涉及外部工具参数变化时，同步更新日志和 `packaging/README.md`。
- 不要在平台 downloader 中重复散写工具发现逻辑。
