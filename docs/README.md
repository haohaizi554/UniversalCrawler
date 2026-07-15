# Universal Crawler Pro 文档中心

这里收纳项目的架构、开发、运行、修复和复盘文档。文档正文统一使用中文，文件名统一使用小写英文 slug；阶段性报告和复盘使用日期前缀，便于按时间排序。

当前文档基线对应源码版本 `3.6.17`，包名与命令行为 `ucrawl`。日常运行优先参考 `main.py`、`entry.gui_entry`、`entry.web_entry`、`entry.cli_entry` 和 `entry.test_entry`；历史复盘中的旧入口或旧流程仅作为问题背景保留。

## 快速入口

| 分类 | 入口 | 内容 |
| --- | --- | --- |
| 架构与开发 | [guides/](guides/README.md) | 架构、接口、配置、测试、打包和开发指南 |
| CLI / SDK | [cli/](cli/README.md) | 命令行、REST API 与 Python SDK 使用说明 |
| 工程实践 | [engineering/](engineering/README.md) | Windows 原生窗口、前端刷新、并发控制和设置控件契约 |
| 修复记录 | [fixes/](fixes/README.md) | GUI、WebUI、配置中心和运行时修复记录 |
| 工程审查 | [reviews/](reviews/README.md) | 架构审查、Qt 前端经验和重构记录 |
| 验收报告 | [reports/](reports/README.md) | 阶段验收、运行基线和合并后的信号运行报告 |
| 事故复盘 | [postmortems/](postmortems/) | 队列、HLS、控件等问题复盘 |
| ADR | [adr/](adr/README.md) | 架构决策记录 |
| Prompt | [prompts/](prompts/README.md) | 历史提示词归档 |
| 更新日志 | [changelog.md](changelog.md) | 版本变更记录 |

## 维护规则

- 正文使用中文；保留英文术语时优先附中文解释。
- 文件名使用小写英文、数字和连字符，例如 `2026-06-28-runtime-baseline.md`。
- 同一主题只保留一个主入口；细节过程放入 `archive/` 或日期化复盘文档。
- 过时设计需要标注当前实现状态，避免让后来维护者照旧文档走错路。
