# 打包态启动未响应与下载目录递归清理复盘

## 事故现象

冻结后的 `UniversalCrawlerPro.exe` 可以画出主窗口，但控件整体发白，Windows 很快提示“未响应”。源码开发态不一定复现，导致问题一度看起来像 PyInstaller、Qt 或资源加载故障。

故障样本的保存根目录误设为 `D:\desktop`。该目录约有 81.3 GB、185352 个文件和 19088 个目录。旧启动逻辑在 `DownloadManager` 构造函数内同步执行 `os.walk(root, topdown=False)`，还会对遍历到的每个子目录尝试 `rmdir()`。窗口虽然已经显示，Qt 事件循环却尚未开始处理消息，因此 Windows 正确地把进程判定为未响应。

## 证据链

1. 打包态日志停在 HLS 孤儿工作区清理附近，没有出现应用就绪事件。
2. `ApplicationController` 在 Qt 事件循环启动前构造 `DownloadManager`。
3. `DownloadManager` 构造函数同步调用普通下载临时文件清理。
4. 普通清理对用户配置根目录执行无边界递归，与故障目录规模直接相关。
5. 开发态与冻结态读取不同用户数据根；开发环境的小目录无法代表 `%LOCALAPPDATA%` 中保存的真实打包配置。

根因不是“Qt 偶发卡死”，而是**在 UI 线程和事件循环启动边界内执行了用户可控规模的文件系统遍历**。

## 当前恢复协议

### 1. 启动线程边界

- `DownloadManager` 构造只创建恢复账本、维护线程和 dispatcher，不扫描文件系统。
- 启动维护在 `download-startup-maintenance` 后台线程运行。
- dispatcher 通过 `threading.Event` 等待维护门闩，避免新任务与孤儿清理竞争；GUI 事件循环不等待该门闩。
- 维护日志失败也不能阻止门闩释放。

### 2. 路径恢复账本

`DownloadRecoveryStore` 使用本地 SQLite，启用 WAL 和 `synchronous=FULL`：

1. dispatcher 在创建 worker 前，先按共享路径策略算出真实保存目录并提交 `active` 行。
2. 提交失败时任务失败关闭，不能继续创建临时文件。
3. 成功完成后立即删除 active 行，不使用按天保留策略。
4. 失败、中止或 worker 构造失败时，把目录原子移交到 `pending_cleanup_directories`，并按路径去重。
5. 下一次启动只扫描这些精确目录；扫描尝试结束后无条件消费 active 和 pending 行，是否实际命中文件不影响销账。

账本保存的是“尚未履行的清理责任”，不是历史记录。没有 TTL，也不会因为应用长时间未打开而把已使用记录留成垃圾。

### 3. 旧版本遗留迁移

旧版本没有账本，只能做一次兼容扫描。当前实现遵守以下边界：

- 普通下载只扫描根目录、合集目录和第二层目录，最大深度固定为 2。
- 不删除普通空目录，不跟随符号链接，只删除严格白名单命名的临时文件或工作目录。
- 扫描前沿持久化到 SQLite；每次启动按预算处理一批目录，崩溃后从未消费的目录继续，而不是从根目录重新开始。
- 切换保存根目录时丢弃旧根的未使用迁移前沿，避免迁移账本无限累积。
- 单目录条目数、总目录数和单轮时间都有上限；触发上限必须写 WARN。

### 4. M3U8 边界

M3U8 外部下载器允许递归处理自己拥有的 `.ucp-nm3u8-tmp`、`*_curl_cffi_hls` 和 `*_playwright_hls` 工作目录。普通下载清理不得借此扩大到任意用户目录。

### 5. 退出线程判定

Python `threading.Thread.join(timeout)` 无论线程是否已退出都返回 `None`。不能写成 `if not thread.join(timeout):`，否则每次正常关闭都会被误记为 dispatcher 超时。正确顺序是先调用 `join(timeout)`，再用 `thread.is_alive()` 判断是否真的超时；回归测试必须模拟真实的 `join() -> None` 语义。

## 为什么不采用并行全盘扫描

并行扫描仍会枚举所有无关文件，只会把元数据随机 I/O、句柄和 CPU 压力同时放大。`os.scandir()` 可以减少额外 `stat` 调用，但不能改变全盘扫描的复杂度；它适合有边界的目录枚举，而不是为错误边界兜底。[Python `os.scandir` 文档](https://docs.python.org/3/library/os.html)

Windows USN Journal 和 `ReadDirectoryChangesW` 可作为将来的增量加速器，但不能成为唯一真相源：USN 依赖 NTFS 卷和日志生命周期，目录变更通知也可能缓冲区溢出并要求重新枚举。[Microsoft USN Journal](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/fsutil-usn)、[ReadDirectoryChangesW](https://learn.microsoft.com/zh-cn/windows/win32/api/winbase/nf-winbase-readdirectorychangesw)

恢复账本选择 SQLite WAL，是因为它把“先记录责任、再产生副作用”的顺序变成可测试事务；`synchronous=FULL` 用于提高异常退出和断电场景下的提交耐久性。[SQLite WAL](https://sqlite.org/wal.html)、[SQLite PRAGMA](https://www.sqlite.org/pragma.html)

## 回归守则

- UI 构造器、Qt slot 和 Web 事件循环禁止递归目录遍历。
- 用户配置路径必须按不可信规模处理；不能用开发机默认目录代表冻结态配置。
- 新临时文件命名必须同时补充白名单清理和生命周期测试。
- 新下载器如果会创建子目录，必须复用 `resolve_task_save_directory()` 或在产生副作用前更新恢复账本。
- 测试必须覆盖：构造不阻塞、dispatcher 等待门闩、提交失败关闭、成功立即销账、失败目录去重、缺失路径也消费、迁移前沿跨重启续跑、普通扫描止于两层。
- 线程关闭测试不得给 `join()` 伪造布尔返回值；必须在 `join()` 后检查 `is_alive()`，避免测试替身掩盖生产误报。
- 发布验收必须用一个大而无关文件很多的保存根启动冻结包，并确认窗口持续响应、日志出现 `DL_STARTUP_MAINTENANCE_DONE`。

## 2026-07-11 冻结包验收

- 使用冻结态真实配置 `save_directory=D:\desktop` 启动新构建的 `UniversalCrawlerPro.exe`。
- 连续 30 秒采样得到 `30/30` 次 `Responding=True`，窗口未自行退出。
- 测试脚本正常关闭窗口后退出码为 `0`。
- 日志同时出现 `DL_STARTUP_MAINTENANCE_START`、`APP_READY` 和 `DL_STARTUP_MAINTENANCE_DONE`。
- 正常关闭日志未出现 `DL_DISPATCHER_STOP_TIMEOUT`。
- 同一稳定源码快照的全量基线为 `2447 passed, 3 skipped, 7 warnings in 257.85s (0:04:17)`。

## 关键实现

- `app/core/download_manager_core.py`
- `app/core/download_path_policy.py`
- `app/services/download_recovery_store.py`
- `app/services/file_service.py`
- `tests/test_download_manager_core.py`
- `tests/test_download_recovery_store.py`
- `tests/test_file_service.py`
