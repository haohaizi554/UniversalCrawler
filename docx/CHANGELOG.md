# 更新日志

本文件记录项目的重要变更。版本号以 `pyproject.toml` 中声明的项目版本为准，格式参考 Keep a Changelog，但内容统一使用中文。

## 未发布

### 新增

- 新增共享打包元数据 `packaging/project_meta.py`。
- 新增维护者发布指南，并统一迁移到 `docx/guides/packaging.md`。
- 新增测试命名规则和高价值 Web、插件、WebSocket 测试。
- 新增仓库级 `LICENSE`、`MANIFEST.in` 和 `.gitattributes`。
- 新增英文 README 作为中文 README 的配套入口。
- 新增 Docker 运行资源，包括 `requirements-web.txt`、`docker/entrypoint.sh` 和 `.env.docker.example`。
- 新增 Docker 构建验证工作流。
- 便携版构建显式打包 `ffprobe.exe` 和 `shared/`，支持媒体元数据服务和跨入口运行时辅助能力。

### 变更

- 安装器版本注入统一读取 `pyproject.toml`。
- README、测试文档和打包文档已按当前项目结构更新。
- 测试自动分类规则覆盖新增 Web 和插件测试。
- 项目许可证说明调整为个人非商业许可。
- 根 README 增补 Docker 使用说明和语言切换链接。
- 打包文档补充 `project_meta.py`、`runtime_paths.py` 以及构建脚本、文档和测试之间的同步契约。
- 桌面媒体删除流程会先释放当前媒体源，避免文件占用导致删除失败。
- 便携版 `portable.spec` 元数据与 `project_meta.py` 对齐，并更新双 EXE 直接启动模型说明。
- `docx/` 文档已整理为长期指南、修复记录、复盘、报告、审查、提示词和 ADR 分层。

### 修复

- 修复抖音 FFmpeg 进度解析和重试刷新行为。
- 修复 Web 侧抖音参数初始化瓶颈和打包元数据漂移。
- 修复 Bilibili spider 线程回归，单个资源流失败不再终止整个任务循环。
- 移除快手、抖音、FFmpeg 和 Web 前端路径中的临时调试探针。
- 补齐小红书路由分发、HTML fallback、461 cooldown 和下载器 header 传递回归覆盖。
- 修复 `ucrawl-auto` 控制台入口，指向 `entry.dispatcher:run`。
