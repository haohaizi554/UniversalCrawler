# 课程要求达标检查

## 总览

下表按老师给出的 6 大项逐条核对当前项目材料与技术实现情况。

| 序号 | 要求 | 当前状态 | 证据 |
| --- | --- | --- | --- |
| 1 | 黑盒测试至少 2 种方法 | 已满足 | `coursework/test_cases.xlsx`、`coursework/report_submission.md` |
| 2 | 白盒测试至少 2 种方法 | 已满足 | `coursework/test_cases.xlsx`、`tests/test_runtime_paths.py`、`tests/test_download_manager_dispatch.py` |
| 3 | 黑白盒用例字段规范并用 Excel 整理 | 已满足 | `coursework/test_cases.xlsx`、`coursework/test_cases_compact.xlsx` |
| 4 | 2 个核心功能单元设计用例 | 已满足 | `coursework/unit_tests/test_ddt_units.py` |
| 5 | `unittest + ddt` 数据驱动 | 已满足 | `coursework/unit_tests/test_ddt_units.py` |
| 6 | `TestSuite` 批量运行 | 已满足 | `coursework/unit_tests/run_course_suite.py`、`tests/run_core_suite.py` |
| 7 | `BeautifulReport` 测试报告 | 已满足 | `coursework/unit_tests/run_course_suite.py`、`coursework/reports/beautiful_report.html` |
| 8 | 2 个核心接口设计与执行 | 已满足 | `coursework/api/interface_docs.md`、`coursework/api/execution_results.md` |
| 9 | 接口文档完整 | 已补齐 | `coursework/api/interface_docs.md` |
| 10 | Postman 材料 | 已满足主要技术要求 | `coursework/api/postman_collection.json`、`coursework/api/postman_environment.json` |
| 11 | Postman 失败截图 | 需人工补图 | 依据 `coursework/evidence_checklist.md` 在 Postman GUI 中补截图 |
| 12 | 2 个 UI 自动化场景 | 已满足 | `coursework/ui_tests/test_sanitize_flow_selenium.py`、`coursework/ui_tests/test_build_filename_flow_selenium.py` |
| 13 | Python + Selenium | 已满足 | `coursework/ui_tests/README.md` 与上述脚本 |
| 14 | 元素定位与断言 | 已满足 | `By.ID`、`By.CSS_SELECTOR`、`By.XPATH` 均已使用 |
| 15 | 传统测试与 AI 测试理解 | 已满足 | `coursework/report_submission.md` 第 12 节 |
| 16 | 报告完整度与格式规范 | 已满足主要内容 | `coursework/report_submission.md` |

## 已补齐但属于“课程适配层”的内容

由于原项目是 PyQt6 桌面应用，并不天然提供 Web API 与浏览器 DOM，因此为满足老师要求，新增了课程专用适配层：

- `coursework/api/mock_api_server.py`
  - 提供 2 个本地 HTTP 接口
  - 底层复用项目真实函数 `sanitize_filename()` 与 `build_media_filename()`
- `coursework/ui_tests/*.py`
  - 基于本地演示页面执行 Selenium UI 自动化
  - 目的在于满足课堂技术要求，而不干扰主项目桌面架构

## 仍建议人工补的内容

以下内容受当前命令行环境限制，建议你在本机图形环境中最后补齐：

- Postman Collection Runner 执行截图
- Postman 异常用例失败截图
- Selenium 脚本运行时浏览器界面截图
- BeautifulReport 生成页面截图
- Word 版报告最终排版截图

## 当前结论

从“技术使用”和“材料完整度”来看，当前项目已经从原先的“项目测试材料”扩展为“更贴合课程要求的交付包”：

- 黑白盒测试：满足
- 单元测试：满足，且已使用 `ddt`
- 批量执行：满足，且已接入 `TestSuite`
- 测试报告：满足，且已生成 `BeautifulReport`
- 接口测试：满足主要内容，Postman GUI 截图需人工补
- UI 自动化测试：满足，且两条 Selenium 脚本已执行通过
- 理论总结：满足，已补入“传统软件测试 vs AI 软件测试”的理解
