# 项目文档中心

> 本目录统一保存 Universal Crawler Pro 的工程文档。所有长期维护文档、修复记录、复盘、报告和提示词均使用中文描述；代码标识、命令、接口路径和第三方工具名称保持原样。

## 阅读顺序

1. [核心技术参考](guides/core-technologies.md)：先理解技术栈、主链路和工程约束。
2. [总体架构](guides/architecture.md)：再看模块分层、数据流和运行边界。
3. [配置说明](guides/config.md)：了解配置中心、热加载和 GUI/WebUI 契约。
4. [测试指南](guides/testing.md)：确认如何运行分组测试和回归测试。
5. [打包与发布指南](guides/packaging.md)：了解便携版、安装包和发布流程。

## 分类索引

| 分类 | 路径 | 内容 |
| --- | --- | --- |
| 长期指南 | [guides/README.md](guides/README.md) | 架构、核心技术、配置、测试、打包、容器、开发规范 |
| CLI/SDK | [cli/](cli/) | 命令行、Python SDK、REST API 参考 |
| 修复整理 | [fixes/README.md](fixes/README.md) | 配置中心、GUI、WebUI 等用户可见问题修复 |
| 事故复盘 | [postmortems/](postmortems/) | 典型异常、根因分析和防回归规则 |
| 架构决策 | [adr/README.md](adr/README.md) | 关键技术决策和取舍 |
| 审查记录 | [reviews/README.md](reviews/README.md) | 架构审查、Qt 前端审查、重构提取记录 |
| 验收报告 | [reports/README.md](reports/README.md) | 运行基线、信号优化、最终验收记录 |
| 提示词归档 | [prompts/README.md](prompts/README.md) | 复杂任务提示词和 UI 重构提示词 |
| 更新日志 | [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |

## 维护规则

- 新增长期说明放入 `guides/`，不要继续堆在 `docx/` 根目录。
- 用户可见 bug 修复放入 `fixes/`，有复盘价值的事故放入 `postmortems/`。
- 大型审查、重构边界和技术债记录放入 `reviews/`。
- 验收、基线、压测和阶段性结论放入 `reports/`。
- 新文档必须用中文说明；代码名、命令、HTTP 路径、类名和第三方库名可以保留英文。
- 移动文档后必须同步 README 和相关相对链接。
