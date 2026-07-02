# CLI / SDK 文档

本目录按使用场景拆分：`cli-guide.md` 是总览和端到端示例，`python-sdk-guide.md` 与 `rest-api-reference.md` 是专项参考。三者有少量概念重复，但不再互相复制完整内容。

| 文档 | 内容 |
| --- | --- |
| [cli-guide.md](cli-guide.md) | 推荐先读：入口模式、参数、二次选择和端到端示例 |
| [python-sdk-guide.md](python-sdk-guide.md) | Python SDK 集成说明 |
| [rest-api-reference.md](rest-api-reference.md) | REST API 调用参考 |

这些文档面向自动化调用和二次开发。GUI/WebUI 的状态与操作应通过统一前端适配层获取，避免直接耦合爬虫或下载核心。
