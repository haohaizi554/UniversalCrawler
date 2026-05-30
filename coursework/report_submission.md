# 《软件测试技术》课程大作业提交稿模板

## 封面信息

- 课程名称：软件测试技术
- 题目：基于 UniversalCrawlerPro 的桌面应用测试设计与实现
- 学生姓名：`待填写`
- 学号：`待填写`
- 班级：`待填写`
- 指导教师：`待填写`
- 提交日期：`待填写`

---

## 摘要

本文以 `UniversalCrawlerPro` 项目为研究对象，围绕桌面端多平台媒体采集与下载系统的核心功能，开展黑盒测试、白盒测试、接口集成测试、UI 测试和验收测试。针对课程要求中对测试方法、测试用例设计、批量执行和测试结果展示的要求，本文不仅完成了基础测试任务，还结合项目真实架构，将 Spider、Controller、DownloadManager、DownloadWorker、配置管理和运行环境路径等高风险模块纳入测试范围。测试结果表明，该项目在关键下载链路、控制器编排、运行环境路径、日志脱敏与异常分支方面具有较高稳定性，同时对于真实站点登录、浏览器行为和打包交付等区域，仍需通过人工验收进一步补强。本文形成了一套更贴近工程实践的桌面应用测试方案。

**关键词**：软件测试；黑盒测试；白盒测试；PyQt6；桌面应用；自动化测试

---

## 1. 引言

随着桌面应用逐渐具备更复杂的网络访问、资源解析、异步下载和本地媒体管理能力，其测试对象已经不再局限于单一函数或简单界面控件。`UniversalCrawlerPro` 作为一个基于 `Python + PyQt6 + Playwright` 实现的多平台媒体采集与下载工具，涉及桌面 GUI、浏览器自动化、任务调度、文件系统 I/O、外部工具调用和日志追踪等多个维度，因此非常适合作为软件测试课程的大作业对象。

本次大作业的核心目标有两层：

1. 满足课程对黑盒测试、白盒测试、测试用例设计、批量执行和测试结果展示的要求；
2. 不局限于课堂范式，而是从真实项目的工程风险出发，建立更完整的测试体系。

---

## 2. 被测系统简介

### 2.1 项目概述

`UniversalCrawlerPro` 是一款面向 Windows 桌面的多平台媒体采集与下载工具。项目提供从资源访问、列表解析、结果勾选、统一下载到本地管理与播放的完整闭环，支持抖音、Bilibili、快手和 MissAV 等平台。

### 2.2 系统特点

- 采用 PyQt6 实现原生桌面界面；
- 采用插件化方式组织平台能力；
- 采用 Spider / Parser / TaskBuilder 三段式处理站点逻辑；
- 采用 DownloadManager / DownloadWorker 统一调度下载任务；
- 支持 `ffmpeg` 与 `N_m3u8DL-RE` 外部工具；
- 提供全链路日志、错误摘要与 trace_id 调试能力。

### 2.3 本次选取的测试重点

- 文件名工具与数据模型
- 平台解析器
- 控制器编排逻辑
- 下载调度与下载生命周期
- 运行环境路径与启动入口
- 配置持久化与日志脱敏

---

## 3. 测试环境与测试工具

### 3.1 硬件与软件环境

- 操作系统：Windows 10 / 11
- Python 版本：3.10 及以上
- 图形界面框架：PyQt6
- 浏览器自动化：Playwright Chromium
- 外部工具：`ffmpeg.exe`、`N_m3u8DL-RE.exe`

### 3.2 测试工具

- 自动化单元测试与集成测试：`unittest`
- 数据驱动单元测试：`ddt`
- 批量套件执行：`unittest.TestSuite`
- 测试报告：`BeautifulReport`
- 接口测试材料：`Postman Collection + Environment`
- UI 自动化测试：`Python + Selenium`
- 文档整理：Markdown + Excel
- 人工验收依据：项目运行截图、日志截图、打包产物截图

### 3.3 测试执行命令

```bash
python -m unittest discover -s tests
python tests/run_core_suite.py
python coursework/unit_tests/run_course_suite.py
python coursework/api/mock_api_server.py
python coursework/api/run_api_checks.py
python coursework/ui_tests/test_sanitize_flow_selenium.py
python coursework/ui_tests/test_build_filename_flow_selenium.py
```

---

## 4. 测试需求分析

课程原始要求主要面向通用软件模块和 Web/接口型项目，但 `UniversalCrawlerPro` 是桌面应用，因此在保持课程目标不变的前提下，对测试需求做如下映射：

- 黑盒测试：面向功能结果与输入输出行为；
- 白盒测试：面向实现分支、异常路径和关键逻辑；
- 接口测试：面向内部模块之间的方法调用链和信号传递；
- UI 测试：面向桌面组件与控制器交互，而非浏览器页面；
- 验收测试：面向真实站点、真实登录态与打包产物。

这种映射既符合课程对测试多样性的要求，也更符合桌面应用的工程现实。

---

## 5. 黑盒测试设计

### 5.1 采用的方法

本次黑盒测试主要采用：

- 等价类划分
- 边界值分析
- 场景法

### 5.2 设计思路

#### 5.2.1 等价类划分

将输入划分为正常类、异常类、空值类和兼容类，例如：

- 文件名输入：合法、非法、空值、超长；
- 解析器输入：完整数据、缺字段数据、错误结构数据；
- 配置输入：合法配置、损坏配置、缺失字段配置。

#### 5.2.2 边界值分析

重点针对数量、长度和状态切换边界进行验证，例如：

- 分页控件最大值与默认值回退；
- 文件名长度上限；
- 下载目录扫描数量上限；
- 主题切换和全屏恢复的状态边界。

#### 5.2.3 场景法

针对较长业务链设计测试场景，例如：

- 解析资源 -> 控制器接收 -> 下载管理器入队；
- Worker 下载 -> 文件签名识别 -> 扩展名修正 -> 完成回调；
- 启动应用 -> 初始化 -> 进入运行态。

---

## 6. 白盒测试设计

### 6.1 目标

本次白盒测试重点不是追求形式上的代码覆盖率数字，而是围绕“高风险实现分支”建立保护网。

### 6.2 重点模块

- `main.py`
- `app/utils/runtime_paths.py`
- `app/core/download_manager.py`
- `app/controllers/application_controller.py`
- `app/debug_logger.py`

### 6.3 覆盖内容

- 语句覆盖：启动入口、路径初始化、基础执行流
- 分支覆盖：冻结环境/非冻结环境、存在/不存在文件、成功/失败调度
- 异常覆盖：启动异常、调度异常、I/O 异常、非法 JSON、日志脱敏异常情况

---

## 7. 接口集成测试设计

原项目是 PyQt6 桌面应用，并不天然提供公开 HTTP 接口。为了满足课程中“接口文档 + Postman + 接口执行”的要求，本次在不修改主业务架构的前提下，新增了课程接口适配层，将项目真实核心函数封装为本地 HTTP 接口。

### 7.1 测试对象

- 接口一：`GET /api/v1/files/sanitize`
- 接口二：`POST /api/v1/media/build-filename`

### 7.2 代表性测试

- 正常场景：非法文件名清洗
- 正常场景：MissAV 文件名生成
- 异常场景：缺少 `source` 参数
- 异常场景：请求方式错误

### 7.3 接口文档与 Postman 资产

- 接口文档：[interface_docs.md](file:///d:/desktop/UniversalCrawlerPro/coursework/api/interface_docs.md)
- Postman Collection：[postman_collection.json](file:///d:/desktop/UniversalCrawlerPro/coursework/api/postman_collection.json)
- Postman Environment：[postman_environment.json](file:///d:/desktop/UniversalCrawlerPro/coursework/api/postman_environment.json)
- 本地执行结果：[execution_results.md](file:///d:/desktop/UniversalCrawlerPro/coursework/api/execution_results.md)

### 7.4 接口执行结果摘要

根据本地执行结果：

- `API-GET-001` 文件名清洗接口：`200`，`77.28 ms`
- `API-POST-001` 媒体文件名生成接口：`200`，`2.08 ms`
- `API-POST-002` 缺少 `source`：`400`，`1.97 ms`
- `API-PUT-001` 请求方式错误：`405`，`1.67 ms`

上述结果说明接口在正常与异常场景下均能返回稳定的状态码与响应结构。

---

## 8. UI 测试设计

课程明确要求使用 `Python + Selenium`。由于主项目不是 Web 应用，本次新增课程 UI 演示层，在浏览器页面中复用了项目真实文件名工具函数，并基于该演示层完成 Selenium 自动化。

### 8.1 自动化 UI 测试

- 场景一：文件名清洗流程
- 场景二：媒体文件名生成流程

### 8.2 Selenium 脚本

- [test_sanitize_flow_selenium.py](file:///d:/desktop/UniversalCrawlerPro/coursework/ui_tests/test_sanitize_flow_selenium.py)
- [test_build_filename_flow_selenium.py](file:///d:/desktop/UniversalCrawlerPro/coursework/ui_tests/test_build_filename_flow_selenium.py)
- [selenium_common.py](file:///d:/desktop/UniversalCrawlerPro/coursework/ui_tests/selenium_common.py)

### 8.3 UI 场景覆盖点

- 浏览器初始化
- 页面跳转
- 元素输入
- 按钮点击
- 页面结果读取
- 断言结果文本
- 循环执行多个测试用例

### 8.4 UI 执行结果

- 文件名清洗脚本：执行成功，输出 `sanitize selenium flow passed`
- 媒体文件名生成脚本：执行成功，输出 `build filename selenium flow passed`
- 结果汇总：[execution_results.md](file:///d:/desktop/UniversalCrawlerPro/coursework/ui_tests/execution_results.md)

### 8.5 人工 UI 验收

- 启动主界面
- 切换不同平台
- 更换保存目录
- 查看下载队列和日志
- 预览图片或播放视频

---

## 9. 验收测试设计

验收测试主要针对真实场景进行，测试数据来源于项目根目录中的 `测试案例.txt`。

### 9.1 场景清单

- 抖音分享链接流程
- Bilibili BV 视频流程
- Bilibili UP 主空间流程
- 快手主页流程
- MissAV 番号流程
- 安装版与绿色版启动冒烟

### 9.2 验收原则

- 看是否能进入正确流程；
- 看是否能展示可下载结果；
- 看是否能稳定完成下载或入队；
- 看是否存在明显 UI 错误或运行崩溃；
- 看日志与错误提示是否可用。

---

## 10. 测试用例与自动化实现

### 10.1 教师查看版精简用例表

- [test_cases_compact.xlsx](file:///d:/desktop/UniversalCrawlerPro/coursework/test_cases_compact.xlsx)

### 10.2 完整用例总表

- [test_cases.xlsx](file:///d:/desktop/UniversalCrawlerPro/coursework/test_cases.xlsx)

### 10.3 核心自动化脚本

- [tests/run_core_suite.py](file:///d:/desktop/UniversalCrawlerPro/tests/run_core_suite.py)
- [tests/test_runtime_paths.py](file:///d:/desktop/UniversalCrawlerPro/tests/test_runtime_paths.py)
- [tests/test_settings_builders.py](file:///d:/desktop/UniversalCrawlerPro/tests/test_settings_builders.py)
- [tests/test_main_entry.py](file:///d:/desktop/UniversalCrawlerPro/tests/test_main_entry.py)
- [tests/test_download_manager_dispatch.py](file:///d:/desktop/UniversalCrawlerPro/tests/test_download_manager_dispatch.py)
- [coursework/unit_tests/test_ddt_units.py](file:///d:/desktop/UniversalCrawlerPro/coursework/unit_tests/test_ddt_units.py)
- [coursework/unit_tests/run_course_suite.py](file:///d:/desktop/UniversalCrawlerPro/coursework/unit_tests/run_course_suite.py)

---

## 11. 测试执行结果与分析

### 11.1 自动化结果

- `python -m unittest discover -s tests`
  - `Ran 211 tests ... OK`
- `python tests/run_core_suite.py`
  - `Ran 175 tests ... OK`
- `python -m unittest coursework.unit_tests.test_ddt_units`
  - `Ran 11 tests ... OK`
- `python coursework/unit_tests/run_course_suite.py`
  - BeautifulReport 已生成：[beautiful_report.html](file:///d:/desktop/UniversalCrawlerPro/coursework/reports/beautiful_report.html)
- `python coursework/api/run_api_checks.py`
  - 4 条接口用例执行通过
- `python coursework/ui_tests/test_sanitize_flow_selenium.py`
  - Selenium 场景一执行通过
- `python coursework/ui_tests/test_build_filename_flow_selenium.py`
  - Selenium 场景二执行通过
- 关键模块结果摘要已保存到 [automation_results.md](file:///d:/desktop/UniversalCrawlerPro/coursework/automation_results.md)
- 原始命令输出已保存到 `coursework/command_outputs/` 目录，便于后续截图和附录整理

### 11.2 结果分析

结果表明：

- 高风险纯逻辑已基本纳入自动化保护；
- 控制器与下载调度协作链路已有明显增强；
- 启动、路径、打包相关逻辑已不再处于测试盲区；
- `ddt`、`TestSuite`、`BeautifulReport`、`Selenium` 等课程要求技术已实际使用；
- 项目测试已具备课程作业要求中的层次感和完整性。

### 11.3 代表性命令证据

- 全量回归：见 [discover.txt](file:///d:/desktop/UniversalCrawlerPro/coursework/command_outputs/discover.txt)
- 核心套件：见 [run_core_suite.txt](file:///d:/desktop/UniversalCrawlerPro/coursework/command_outputs/run_core_suite.txt)
- 黑盒代表用例：见 [test_utils_filenames.txt](file:///d:/desktop/UniversalCrawlerPro/coursework/command_outputs/test_utils_filenames.txt)
- 白盒代表用例：见 [test_runtime_paths.txt](file:///d:/desktop/UniversalCrawlerPro/coursework/command_outputs/test_runtime_paths.txt)
- 接口集成代表用例：见 [test_integration_flows.txt](file:///d:/desktop/UniversalCrawlerPro/coursework/command_outputs/test_integration_flows.txt)
- UI 代表用例：见 [test_main_window.txt](file:///d:/desktop/UniversalCrawlerPro/coursework/command_outputs/test_main_window.txt) 与 [test_download_queue_panel.txt](file:///d:/desktop/UniversalCrawlerPro/coursework/command_outputs/test_download_queue_panel.txt)
- 课程单元测试结果：见 [execution_results.md](file:///d:/desktop/UniversalCrawlerPro/coursework/unit_tests/execution_results.md)
- 课程接口测试结果：见 [execution_results.md](file:///d:/desktop/UniversalCrawlerPro/coursework/api/execution_results.md)
- 课程 UI 自动化结果：见 [execution_results.md](file:///d:/desktop/UniversalCrawlerPro/coursework/ui_tests/execution_results.md)

---

## 12. 传统软件测试与 AI 软件测试的理解

传统软件测试强调基于需求、设计、代码和运行行为的系统化验证，其核心在于：

- 明确测试目标与测试边界；
- 通过等价类、边界值、判定表、语句覆盖、分支覆盖等方法构造测试；
- 强调可复现、可追踪、可审计；
- 注重测试用例、缺陷记录和测试报告的规范化。

AI 软件测试则更强调智能辅助和自动化增效，其优势主要体现在：

- 能快速分析代码结构并发现薄弱测试区域；
- 能辅助生成测试用例草稿、测试数据和测试脚本；
- 能对大规模代码进行语义搜索和风险聚焦；
- 能帮助整理测试报告、接口文档和交付材料。

但 AI 测试并不能替代传统测试工程方法。原因在于：

- AI 可能生成看似合理但并不贴合真实业务边界的测试；
- AI 对课程要求中的“截图证据”“人工验收”“失败原因分析”仍需人工把关；
- 真正高质量的测试仍然依赖测试人员对业务、架构、风险和场景的理解。

因此，较合理的理解应当是：

- 传统软件测试提供方法论和质量底线；
- AI 软件测试提升分析、补测、文档和脚本编写效率；
- 二者结合，才能形成“有方法、有证据、有工程价值”的测试体系。

---

## 13. 存在的问题与后续改进

目前仍需通过人工方式进一步验证的部分包括：

- 真实站点登录态；
- 浏览器页面滚动与动态资源捕获；
- 外部工具真实执行兼容性；
- 打包产物在不同机器上的运行表现。

后续如继续完善，可考虑：

- 接入覆盖率报告；
- 增强真实环境 smoke 测试；
- 增加更完整的 UI 交互回放或自动化脚本。

---

## 14. 结论

本次大作业测试工作并未局限于课程要求中的通用模板，而是在尊重课程目标的同时，结合 `UniversalCrawlerPro` 的桌面端架构进行了合理扩展。最终形成了“黑盒 + 白盒 + 接口集成 + UI + 验收 + 批量套件”的综合测试方案，不仅满足课程提交要求，也更接近真实项目的严谨测试实践。

---

## 15. 附件与截图建议

- 课程报告原始草稿：[coursework/report.md](file:///d:/desktop/UniversalCrawlerPro/coursework/report.md)
- 截图清单：[coursework/evidence_checklist.md](file:///d:/desktop/UniversalCrawlerPro/coursework/evidence_checklist.md)
- 今日执行顺序清单：[coursework/screenshot_plan.md](file:///d:/desktop/UniversalCrawlerPro/coursework/screenshot_plan.md)
- 自动化结果摘要：[coursework/automation_results.md](file:///d:/desktop/UniversalCrawlerPro/coursework/automation_results.md)
- 达标审计：[coursework/requirements_audit.md](file:///d:/desktop/UniversalCrawlerPro/coursework/requirements_audit.md)

建议提交前补齐：

- 封面
- 学号姓名班级
- 关键自动化结果截图
- 真实验收截图
- 打包产物截图
