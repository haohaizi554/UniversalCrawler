# 测试指南

## 测试目标

当前项目测试主要承担三类职责：

- 保护高频重构区域，避免控制流回归。
- 保护高风险爬虫逻辑，尤其是登录、取流、任务装配和入队。
- 保护文件落盘与 UI 编排的关键边界。

## 课程作业映射

针对“软件测试技术”课程作业的常见要求，当前项目采用如下映射方式：

- 黑盒测试：重点覆盖控制器输入输出、下载器策略选择、配置回读、文件服务行为等可观察结果。
- 白盒测试：重点覆盖 `parser.py`、`task_builder.py`、`DownloadWorker`、`runtime_paths.py`、启动入口和异常分支。
- 批量运行：除 `discover` 之外，额外提供 `tests/run_core_suite.py` 作为 `TestSuite` 入口，便于课程展示和回归联调。
- 接口测试：项目以桌面端内部模块协作为主，测试时将 Spider、Controller、DownloadManager、Service 之间的方法调用链视为内部接口进行验证。
- UI 测试：项目为 PyQt6 桌面应用，不采用 Web Selenium 方案，优先使用组件级和控制器级测试验证 UI 交互逻辑。

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

如果需要按课程作业展示“批量套件运行”，可执行：

```bash
python tests/run_core_suite.py
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
- 启动入口、运行环境路径与打包相关路径解析。
- 插件配置控件与运行参数持久化行为。
- 下载调度线程的派发、槽位释放与失败回传。

## 新增测试时的文档要求

新增测试文件或改变测试策略后，请同步更新：

- `tests/README.md`
- 根目录 `README.md`
- 本文档
