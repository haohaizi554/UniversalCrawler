# UniversalCrawlerProPlus Mermaid 图谱

本目录用于从不同视角全面展示项目结构、运行时编排、下载链、Web/CLI/SDK、事件流、测试与交付形态。

## 图谱索引

- [01-system-overview.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/01-system-overview.md): 项目总览与核心数据流
- [02-entrypoints-and-hosts.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/02-entrypoints-and-hosts.md): 多入口与多宿主运行模式
- [03-controller-and-events.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/03-controller-and-events.md): 控制器组合根与事件桥接
- [04-plugin-and-spider-pipeline.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/04-plugin-and-spider-pipeline.md): 插件发现、Spider 三段式与平台流程
- [05-download-pipeline.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/05-download-pipeline.md): 下载链、策略链与外部工具
- [06-web-runtime.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/06-web-runtime.md): Web REST/WebSocket 工作流
- [07-cli-sdk-runtime.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/07-cli-sdk-runtime.md): CLI / SDK / shared runtime 关系
- [08-data-models-and-context.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/08-data-models-and-context.md): 核心数据模型与状态机
- [09-testing-and-quality.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/09-testing-and-quality.md): 测试分层与质量保障
- [10-packaging-and-delivery.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/10-packaging-and-delivery.md): 打包、发布与交付模式

## 使用建议

- 先看 `01` 和 `05`，快速建立全局结构与下载主链认知。
- 再看 `06` 和 `07`，理解 Web 与 CLI/SDK 是如何复用统一运行时骨架的。
- 最后结合 `03`、`08`、`09` 理解状态流、领域事件和测试保护网。
