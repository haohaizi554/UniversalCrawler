# 自动化命令执行结果

以下结果为 2026-05-31 在当前项目工作区重新执行得到，可直接用于课程报告引用。所有原始输出均保存在 `coursework/command_outputs/`。

## 主项目全量回归

- 命令：`python -m unittest discover -s tests`
- 输出文件：`coursework/command_outputs/discover_latest.txt`
- 结论：`Ran 211 tests in 6.840s`，`OK`

## 主项目核心套件

- 命令：`python tests/run_core_suite.py`
- 输出文件：`coursework/command_outputs/run_core_suite_latest.txt`
- 结论：`Ran 175 tests in 6.789s`，`OK`

## 课程 ddt 单元测试

- 命令：`python -m unittest coursework.unit_tests.test_ddt_units`
- 输出文件：`coursework/command_outputs/course_ddt_latest.txt`
- 结论：`Ran 11 tests`，`OK`

## TestSuite + BeautifulReport

- 命令：`python coursework/unit_tests/run_course_suite.py`
- 输出文件：`coursework/command_outputs/beautiful_report_latest.txt`
- 报告文件：`coursework/reports/beautiful_report.html`
- 结论：测试套件通过并生成 HTML 报告。

## 本地接口执行

- 命令：`python coursework/api/run_api_checks.py`
- 输出文件：`coursework/command_outputs/api_checks_latest.txt`
- 结果文件：`coursework/api/execution_results.md`
- 结论：4 条接口用例全部通过，覆盖 GET 查询、POST 提交、缺参异常和请求方式错误。

## Postman/Newman 批量执行

- 命令：`newman run coursework/api/postman_collection.json -e coursework/api/postman_environment.json`
- 输出文件：`coursework/command_outputs/newman_latest.txt`
- JSON 报告：`coursework/api/newman_report.json`
- 结论：4 requests、7 assertions、0 failed，平均响应时间约 11 ms。

## Selenium UI 自动化

- 场景一命令：`python coursework/ui_tests/test_sanitize_flow_selenium.py`
- 场景二命令：`python coursework/ui_tests/test_build_filename_flow_selenium.py`
- 输出文件：
  - `coursework/command_outputs/selenium_sanitize_latest.txt`
  - `coursework/command_outputs/selenium_build_filename_latest.txt`
- 截图目录：`coursework/evidence/selenium/`
- 结论：两个独立 UI 场景均执行通过，并保存 4 张浏览器截图。
