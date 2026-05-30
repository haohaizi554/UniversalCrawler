# 课程交付物说明

本目录用于承载“软件测试技术”课程大作业相关材料，尽量做到：

- 既满足课程要求中的黑盒、白盒、接口、UI、验收与批量执行说明。
- 又贴合 `UniversalCrawlerPro` 作为 PyQt6 桌面项目的真实测试结构。
- 便于后续导出为 Word、Excel 和 PDF 版本。

## 文件清单

- `test_cases.xlsx`
  - 测试用例总表。
  - 适合直接提交给老师或继续在 Excel 中编辑。
- `test_cases.csv`
  - 测试用例总表的 UTF-8 备份版本。
  - 便于脚本处理、版本对比或再次导入 Excel。
- `test_cases_compact.xlsx`
  - 教师快速查看版精简用例表。
  - 适合直接插入报告正文或课堂展示。
- `test_cases_compact.csv`
  - 精简用例表的 UTF-8 备份版本。
- `report.md`
  - 课程大作业报告草稿。
  - 已覆盖项目简介、测试环境、黑盒/白盒设计、接口与 UI 测试映射、执行结果和结论。
- `report_submission.md`
  - 更接近正式提交结构的版本。
  - 适合复制到 Word 后直接进一步排版。
- `requirements_audit.md`
  - 课程要求达标检查表。
  - 用于核对哪些技术已经使用、哪些截图仍需人工补齐。
- `evidence_checklist.md`
  - 截图、日志、运行结果和提交材料清单。
  - 便于你最后补图、整理电子版和打印版。
- `screenshot_plan.md`
  - 今日执行顺序清单。
  - 用来快速补齐最重要的一批截图。
- `automation_results.md`
  - 自动化命令执行摘要。
  - 记录了全量回归、核心套件和关键测试模块的实际运行结果。
- `unit_tests/execution_results.md`
  - `ddt + TestSuite + BeautifulReport` 的执行结果说明。
- `api/execution_results.md`
  - 课程接口测试的实际响应与响应时间记录。
- `ui_tests/execution_results.md`
  - 两条 Selenium 场景脚本的执行结果说明。

## 推荐整理方式

建议最终提交时，将整个项目中的课程材料整理为如下结构：

```text
学号+姓名+班级/
├── 报告/
│   ├── 软件测试课程大作业报告.docx
│   └── 软件测试课程大作业报告.pdf
├── 测试用例/
│   ├── test_cases.xlsx
│   └── evidence_checklist.md
├── 代码/
│   ├── app/
│   ├── tests/
│   ├── docs/
│   └── main.py
└── 说明/
    ├── README.md
    └── 测试运行结果截图/
```

## 建议操作

1. 优先使用 `test_cases.xlsx` 和 `test_cases_compact.xlsx` 作为提交版表格。
2. 将 `report_submission.md` 复制到 Word 中排版，补齐封面、学号、姓名、班级和截图。
3. 按 `evidence_checklist.md` 逐项补充截图。
4. 若老师要求纸质版，建议把报告正文、关键测试用例表和结果截图放入纸质版。
