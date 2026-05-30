# UniversalCrawlerPro 软件测试课程大作业报告草稿

## 1. 基本信息

- 课程名称：软件测试技术
- 项目名称：UniversalCrawlerPro
- 项目类型：Python + PyQt6 桌面端多平台媒体采集与下载工具
- 学生姓名：`待填写`
- 学号：`待填写`
- 班级：`待填写`
- 指导教师：`待填写`

## 2. 项目概述

`UniversalCrawlerPro` 是一个面向 Windows 桌面环境的多平台媒体采集与下载工具。项目基于 `Python`、`PyQt6` 与 `Playwright` 构建，提供从站点访问、资源解析、任务勾选、统一下载调度到本地媒体管理的完整闭环。

与传统的命令行脚本相比，该项目更强调以下工程能力：

- 桌面端图形界面交互；
- 多平台 Spider 的统一抽象；
- 下载策略自动分发；
- 全链路日志与错误摘要；
- 测试友好与打包交付能力。

## 3. 选题说明与测试对象

课程要求中通常建议选择若干“核心模块”开展黑盒与白盒测试。结合本项目结构，本次测试对象不局限于单一函数，而是选取了如下高价值区域：

### 3.1 核心功能模块

- 平台解析模块：抖音、B 站、快手、MissAV 的 `parser` / `task_builder` / 局部 Spider 逻辑
- 下载模块：`DownloadWorker`、`DownloadManager`、各平台 `Downloader`
- 控制器模块：`ApplicationController`
- 配置与运行环境模块：`settings.py`、`runtime_paths.py`
- 调试与日志模块：`debug_logger.py`

### 3.2 测试重点

- 功能正确性：输入、解析、入队、下载、落盘是否符合预期
- 边界与异常行为：空值、坏配置、错误路径、下载失败、非法参数
- 模块协作正确性：Spider 与 Controller、Controller 与 DownloadManager、Worker 与文件系统之间的数据传递
- 启动与运行环境稳定性：冻结环境路径、启动失败日志、外部工具路径

## 4. 测试环境

### 4.1 软件环境

- 操作系统：Windows 10 / 11
- Python：3.10+
- GUI 框架：PyQt6
- 浏览器自动化：Playwright Chromium
- 测试框架：`unittest`

### 4.2 项目依赖

- `ffmpeg.exe`
- `N_m3u8DL-RE.exe`
- Playwright Chromium 内核

### 4.3 测试执行命令

全量执行：

```bash
python -m unittest discover -s tests
```

课程展示用核心套件：

```bash
python tests/run_core_suite.py
```

## 5. 测试方法设计

## 5.1 黑盒测试设计

本项目选择以下黑盒方法：

### 5.1.1 等价类划分

用于划分不同输入类别，验证系统在不同输入组上的行为是否一致。

应用示例：

- 文件名清洗：合法文件名、非法字符文件名、空文件名、超长文件名
- 解析器输入：合法资源、缺字段资源、无音频资源、错误结构资源
- 配置输入：正确配置、缺字段配置、损坏配置

### 5.1.2 边界值分析

用于验证关键边界场景是否处理正确。

应用示例：

- 分页控件最大值回退到 `max`
- 文件名长度截断到上限
- 下载目录扫描数量限制
- 控制器在缺失本地文件时的重命名回退

### 5.1.3 场景法

用于描述较长的用户操作流或跨模块业务流。

应用示例：

- Spider 发出资源 -> Controller 接收 -> DownloadManager 入队
- DownloadWorker 下载 -> 修正扩展名 -> 通知完成
- 启动应用 -> 初始化控制器 -> 进入运行态

## 5.2 白盒测试设计

本项目选择以下白盒目标：

### 5.2.1 语句覆盖

对关键入口代码进行语句级执行验证：

- `main.main()`
- `runtime_paths.user_data_root()`
- `DownloadManager.add_task()`

### 5.2.2 分支覆盖

对包含明显条件分支或异常分支的代码进行分支验证：

- `runtime_paths.install_root()` 的 frozen / 非 frozen 分支
- `runtime_paths.resource_root()` 的 `_MEIPASS` 分支
- `ApplicationController.on_delete_video()` 的删除成功 / 删除失败分支
- `ApplicationController.on_rename_video()` 的文件存在 / 文件缺失分支
- `DownloadManager._dispatch_loop()` 的正常派发 / 调度失败分支
- `main._set_windows_app_user_model_id()` 的 Windows / 非 Windows 分支

### 5.2.3 异常路径覆盖

重点覆盖以前容易遗漏但真实工程中高风险的异常行为：

- 启动失败时日志记录与异常重抛
- 调度失败时错误回传
- 非法 JSON 配置 / Cookie 文件处理
- 文件删除失败、扩展名重命名失败等 I/O 异常

## 6. 测试用例设计说明

完整测试用例见：

- [test_cases.xlsx](file:///d:/desktop/UniversalCrawlerPro/coursework/test_cases.xlsx)

本次测试用例总表采用课程友好的 Excel 结构，字段包括：

- 用例 ID
- 测试层次
- 测试类型
- 测试模块
- 测试标题
- 前置条件
- 输入数据
- 预期结果
- 实际结果
- 测试状态
- 执行方式
- 对应脚本或证据

## 7. 自动化测试实现

## 7.1 单元测试

已新增或补强如下测试：

- `tests/test_runtime_paths.py`
- `tests/test_settings_builders.py`
- `tests/test_main_entry.py`
- `tests/test_download_manager_dispatch.py`
- `tests/test_application_controller.py`

这些测试主要负责：

- 验证关键纯逻辑函数；
- 验证异常分支与负路径；
- 验证运行环境与启动相关行为；
- 验证下载调度与控制器编排。

## 7.2 批量套件

为满足课程对 `TestSuite` 批量执行的要求，额外编写：

- `tests/run_core_suite.py`

该脚本将核心测试模块打包为统一套件，便于课堂演示、报告截图与阶段验收。

## 7.3 内部接口集成测试

由于本项目不是典型 Web API 系统，而是桌面端应用，因此“接口测试”采用模块间内部接口验证方式进行替代。重点包括：

- `Spider.emit_video()` 与控制器接收链路；
- `Parser -> Controller -> DownloadManager` 的数据传递；
- `DownloadWorker` 完成后回调与状态回写；
- 配置与认证服务的数据保存与回读一致性。

## 8. UI 测试设计说明

课程要求中提到 Selenium + Web UI 的测试方式，但本项目属于 PyQt6 桌面应用，因此采用了更合理的替代方案：

- 组件级测试：验证窗口、表格、主题切换、全屏状态恢复
- 控制器级测试：验证 UI 操作与控制器调用的衔接
- 人工验收测试：验证真实桌面交互与多平台流程

已自动化覆盖的 UI 场景包括：

- 主题切换与持久化
- 全屏退出与状态恢复
- 下载队列表格状态刷新

仍建议人工执行的 UI 场景包括：

- 多平台切换
- 保存目录切换
- 真实媒体播放与图片预览
- 打包产物启动后的界面冒烟

## 9. 真实场景与验收测试设计

结合项目根目录中的 [测试案例.txt](file:///d:/desktop/UniversalCrawlerPro/%E6%B5%8B%E8%AF%95%E6%A1%88%E4%BE%8B.txt)，本报告准备了若干真实验收场景：

- 抖音分享链接采集
- Bilibili BV 视频采集
- Bilibili UP 主空间扫描
- 快手主页扫描
- MissAV 番号流程
- 绿色版与安装版启动冒烟

这些场景需要结合真实网络、浏览器登录态、外部工具环境和界面截图，因此更适合作为人工验收测试部分。

## 10. 测试执行结果

### 10.1 自动化执行结果

本次补测完成后，执行结果如下：

- 全量回归：
  - `python -m unittest discover -s tests`
  - 结果：`Ran 211 tests ... OK`
- 核心课程套件：
  - `python tests/run_core_suite.py`
  - 结果：`Ran 175 tests ... OK`

### 10.2 结果分析

从执行结果来看：

- 核心下载链路和控制器编排已具备较强保护；
- 运行环境路径、启动入口、插件设置与调度线程等过去覆盖偏薄的区域已纳入自动化测试；
- 项目不再仅仅依赖业务 happy path，而是对异常路径和边界条件建立了明确保护网。

## 11. 缺陷与风险分析

虽然自动化测试已较完整，但仍存在以下需要人工补充验证的区域：

- 真实站点登录与浏览器交互
- 真实外部工具可执行性与参数兼容性
- 大量资源场景下的 UI 交互体验
- 网络抖动、Cookie 失效、代理异常等真实环境因素

这些内容不适合完全纳入稳定的 CI 自动化，因此在课程交付中建议通过截图、日志和人工验收记录体现。

## 12. 结论

本次测试工作没有局限于课程要求中对黑盒、白盒、接口、UI 的文字描述，而是结合 `UniversalCrawlerPro` 的桌面应用架构进行了更符合工程实际的扩展：

- 对关键功能进行了黑盒验证；
- 对复杂分支与异常路径进行了白盒覆盖；
- 对 Spider、Controller、DownloadManager、Worker 之间的协作链路进行了集成验证；
- 对桌面 UI 场景采用组件级自动化与人工验收相结合的策略；
- 对课程要求中的批量运行测试，补充了 `TestSuite` 入口。

整体上，本项目已经形成了“自动化为主、人工验收补强、文档与证据配套”的严谨测试体系，能够较好支撑课程大作业的提交与展示。

## 13. 附录

### 13.1 相关文件

- [coursework/README.md](file:///d:/desktop/UniversalCrawlerPro/coursework/README.md)
- [coursework/test_cases.xlsx](file:///d:/desktop/UniversalCrawlerPro/coursework/test_cases.xlsx)
- [coursework/automation_results.md](file:///d:/desktop/UniversalCrawlerPro/coursework/automation_results.md)
- [coursework/evidence_checklist.md](file:///d:/desktop/UniversalCrawlerPro/coursework/evidence_checklist.md)
- [docs/testing.md](file:///d:/desktop/UniversalCrawlerPro/docs/testing.md)
- [tests/run_core_suite.py](file:///d:/desktop/UniversalCrawlerPro/tests/run_core_suite.py)

### 13.2 报告完善建议

正式提交前建议补齐：

- 封面页
- 学号、姓名、班级
- 黑盒和白盒测试结果截图
- `discover` 与 `TestSuite` 的运行结果截图
- 真实场景验收截图
- 安装版与免安装版启动截图
