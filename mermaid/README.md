# UniversalCrawlerProPlus Mermaid 图谱

本目录基于项目当前实际代码分析，从不同视角全面展示项目结构、运行时编排、下载链、Web/CLI/SDK、事件流、测试与交付形态。

## 图谱索引

- [01-system-overview.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/01-system-overview.md): 项目全景分层架构、核心数据流时序、代码量分布饼图
- [02-entrypoints-and-hosts.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/02-entrypoints-and-hosts.md): dispatcher 多源优先级路由、6 种入口模式、宿主共享核心、shared 中立层
- [03-controller-and-events.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/03-controller-and-events.md): 8 个 Mixin 组合根、三层事件体系、事件传播时序、事件分级、生命周期关闭顺序
- [04-plugin-and-spider-pipeline.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/04-plugin-and-spider-pipeline.md): SPI 自动注册、插件类图、Spider 三段式、5 平台能力地图、代码量柱状图
- [05-download-pipeline.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/05-download-pipeline.md): 下载主链、策略链决策树（M3U8→Chunked→FFmpeg→HTTP）、策略链时序、下载器类层次、进度回传机制
- [06-web-runtime.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/06-web-runtime.md): Web 组合根、WebSocket 12 种消息分发器、会话管理、直接下载生命周期、Web 层文件结构
- [07-cli-sdk-runtime.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/07-cli-sdk-runtime.md): 跨端共享运行时骨架、命令分发、6 种选择策略、SDK API、AI Skill 集成
- [08-data-models-and-context.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/08-data-models-and-context.md): VideoItem/DownloadContext/DomainEvent 类图、22 字段分组、下载/爬虫状态机、24 个异常类层次
- [09-testing-and-quality.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/09-testing-and-quality.md): 测试代码分布饼图、测试分层、注册表系统、质量护栏、AEMM 成熟度评级
- [10-packaging-and-delivery.md](file:///d:/desktop/project/UniversalCrawlerProplus/mermaid/10-packaging-and-delivery.md): 交付矩阵、打包流程、Docker 容器化、CI/CD 流水线、发布序列

## 使用建议

- 先看 `01` 建立全局认知，再看 `05` 理解下载主链和策略链
- 看 `03` 理解 8 Mixin 组合根和三层事件体系（项目最核心的架构设计）
- 看 `04` 理解 SPI 自动注册和 Spider 三段式
- 看 `06` 和 `07` 理解 Web 与 CLI/SDK 如何复用统一运行时骨架
- 结合 `08`、`09` 理解数据模型、状态机和测试保护网
- `10` 了解打包与交付形态

## 更新说明

本版图谱基于 2026-06-23 的全量代码分析更新，主要变化：

1. **01**: 新增分层架构图（含 Services 层）、核心数据流改为并行时序图、新增代码量饼图
2. **02**: 新增 dispatcher 多源优先级路由、6 种入口模式 mindmap、shared 中立层详细图
3. **03**: Mixin 从 5 个更新为 8 个、新增三层事件体系图、事件传播时序图、事件分级图、生命周期关闭顺序
4. **04**: 新增 SPI 自动注册机制图、插件类图、平台代码量柱状图、BaseSpider 内部结构
5. **05**: 新增策略链决策树、策略链时序图、下载器类层次（含 Protocol）、进度回传机制
6. **06**: 新增 Web 组合根、WebSocket 12 种消息分发器、会话管理、Web 层文件结构
7. **07**: 新增 SDK API 图、AI Skill 集成图、选择策略类图
8. **08**: DownloadContext 从 10 字段更新为 22 字段、新增异常体系 24 类层次图
9. **09**: 新增测试代码分布饼图、测试注册表系统、AEMM 成熟度评级图
10. **10**: 新增 Docker 容器化图、CI/CD 流水线图
