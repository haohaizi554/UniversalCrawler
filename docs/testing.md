# 测试指南

## 测试目标

当前项目测试主要承担三类职责：

- 保护高频重构区域，避免控制流回归。
- 保护高风险爬虫逻辑，尤其是登录、取流、任务装配和入队。
- 保护文件落盘与 UI 编排的关键边界。

## 测试分层

### 单元测试

适合对象：

- `parser.py`
- `task_builder.py`
- `DownloadWorker` 纯逻辑函数
- 配置与文件名工具

特征：

- 无真实网络
- 无真实站点
- 只验证输入输出与异常行为

### 半集成测试

适合对象：

- `ApplicationController`
- `BiliAPI.get_play_url()` 回退
- `KuaishouSpider._run_capture_pipeline()`
- `MissAVSpider._scan_pages()`

特征：

- mock 浏览器 page/context
- mock 下载器和 UI
- 验证跨模块编排是否正确

### 人工验证

仍建议人工验证以下场景：

- 真实浏览器登录
- 外部工具 `ffmpeg` 与 `N_m3u8DL-RE` 的环境可用性
- UI 交互体验与主题样式

## 运行方式

```bash
python -m unittest discover -s tests
```

如果只运行单个文件：

```bash
python -m unittest tests.test_spider_helpers
python -m unittest tests.test_downloaders
python -m unittest tests.test_application_controller
```

## 推荐 mock 边界

- `Spider`：mock `page`、`context`、`response`、`request`。
- `ApplicationController`：mock `window`、`dl_manager`、`file_service`。
- `DownloadWorker`：优先真实临时目录，少 mock 文件系统纯逻辑。
- `BiliAPI`：mock `requests.Session.get()` 返回值。

## 高价值补测点

优先级较高的区域包括：

- B 站 API 回退与多阶段任务装配。
- 快手实时流捕获与焦点匹配。
- MissAV 双轮扫描与优先级选择。
- 下载完成后的扩展名修正和路径冲突处理。
- controller 对爬虫与下载器之间的衔接。

## 新增测试时的文档要求

新增测试文件或改变测试策略后，请同步更新：

- `tests/README.md`
- 根目录 `README.md`
- 本文档
