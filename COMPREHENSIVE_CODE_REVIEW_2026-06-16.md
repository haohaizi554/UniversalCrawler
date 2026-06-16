# UniversalCrawlerProplus 全面代码审查报告

审查日期：2026-06-16  
审查范围：`app/`、`shared/`、`cli/`、`entry/`、`ucrawl/`、`tests/`、`Dockerfile`、`docker-compose.yml`、依赖配置与 Web/CLI/SDK 主流程。  
审查重点：Bug、潜在安全漏洞、架构边界、依赖供应链、测试与工业级改造路线。

## 1. 总体结论

当前项目已经具备较完整的产品雏形：桌面 GUI、CLI、SDK、FastAPI/WebSocket Web UI、下载器、插件式平台适配、Docker 部署和一批自动化测试。但从工业级项目标准看，安全边界和架构边界还没有完全收敛，尤其是 Web 模式下的会话认证、WebSocket 与 REST 权限不一致、路径访问、任意 URL 下载、凭据处理和依赖治理。

最高优先级应先处理以下 5 类问题：

1. Web 会话认证不是实际意义上的访问控制，Docker 默认 `0.0.0.0` 暴露后风险很高。
2. WebSocket 入口绕过 REST 已有的目录与 `save_dir` 授权校验。
3. 直链下载缺少网络访问策略，存在 SSRF/内网探测/任意响应落盘风险。
4. 本地文件扫描、重命名、删除、文件响应缺少统一的最终路径授权策略。
5. Cookie/凭据仍可能进入前端传输、日志和明文文件，存在账号泄漏风险。

## 2. 验证情况

已执行：

```powershell
python --version
python -m compileall -q app cli entry shared ucrawl
python -m pytest -q tests/test_fastapi_endpoints.py tests/test_web_workflows.py tests/test_web_session_runtime.py tests/test_websocket_server.py tests/test_download_manager_core.py tests/test_downloaders.py tests/test_config_settings.py tests/test_auth_service.py tests/test_utils_filenames.py
python -m pytest -q
python -m pip check
python -m pip_audit --version
python -m bandit --version
python -m ruff check .
```

结果：

- Python 版本：`3.13.2`。
- `compileall`：通过。
- 聚焦测试：`231 passed in 17.92s`。
- 全量 `pytest`：约 124 秒超时，未得到完整结果。
- `pip check`：失败，当前环境存在多项依赖冲突。
- `pip-audit`：未安装。
- `bandit`：未安装。
- `ruff`：未安装。

`pip check` 暴露的主要冲突：

- `f2 0.0.1.7` 要求 `httpx==0.27.2`，当前为 `0.28.1`；要求 `rich==13.9.3`，当前为 `14.1.0`。
- `moviepy`、`opencv-python`、`numba` 与当前 `numpy/pillow` 版本存在冲突。
- `pyopenssl` 与 `cryptography` 版本不匹配。
- `grpcio-tools` 与 `protobuf` 版本不匹配。
- 当前环境还有其他与项目无关但会污染验证结果的包冲突。

建议后续用独立虚拟环境或容器重新跑全量测试和安全扫描，避免全局 Python 环境影响结论。

## 3. 风险总览

| 编号 | 严重级别 | 类型 | 位置 | 摘要 |
|---|---:|---|---|---|
| CR-001 | P0 | 认证/暴露面 | `app/web/rest_router.py`、`app/web/http_session.py`、`Dockerfile` | `/api/session/bootstrap` 无真实认证即返回 token，Docker 默认绑定 `0.0.0.0` |
| CR-002 | P0 | 权限绕过 | `app/web/ws_dispatcher.py` | WebSocket 绕过 REST 的目录和 `save_dir` 授权 |
| CR-003 | P0 | SSRF/任意下载 | `app/web/workflow_download_request_service.py`、`app/core/downloaders/*` | 直链下载缺少 URL/域名/IP 策略 |
| CR-004 | P0/P1 | 文件系统 | `app/services/file_service.py`、`app/web/file_response_service.py` | 扫描会创建目录，删除/重命名/响应文件缺少统一最终路径授权 |
| CR-005 | P1 | 凭据泄漏 | `app/models/video_item.py`、`app/core/lib/douyin/interface/template.py` | Cookie 可能进入 API/WS 响应和日志 |
| CR-006 | P1 | 供应链 | `requirements*.txt`、`Dockerfile`、外部工具 | 未锁版本/哈希，镜像浮动，外部二进制可执行面较大 |
| CR-007 | P1 | CSRF/本地 Web | `app/web/server.py`、`app/web/session_runtime.py` | 允许任意 `localhost:*` 源，Cookie 可跨端口发送 |
| CR-008 | P2 | 调试接口 | `app/web/rest_router.py` | `/api/debug/trigger-select` 暴露在正式路由 |
| CR-009 | P2 | 并发/数据一致性 | `app/core/download_manager.py` | 下载文件名去重非原子，并发下可能覆盖/串写 |
| CR-010 | P2 | 任务生命周期 | `shared/sdk_runtime.py`、`app/core/download_manager_core.py` | 超时取消后后台线程/进程可能未完全终止 |
| CR-011 | P2 | 输入限制/DoS | Web API、扫描服务 | 缺少统一请求模型、大小限制、速率限制 |
| CR-012 | P2 | 配置变更 | `app/web/controller_config_service.py`、`app/config/settings.py` | Web 可改动敏感路径类配置，缺少能力级授权 |
| CR-013 | P3 | 兼容性 | `app/web/session_runtime.py` | Origin 解析不支持 `::1`，无 Origin 又默认通过 |
| CR-014 | P3 | WebSocket 稳定性 | `app/web/ws_transport.py` | 连接列表并发修改、无背压和消息大小控制 |
| CR-015 | P3 | 工程治理 | 全项目 | 静态扫描/安全扫描/锁文件/编码规范不足 |

## 4. 详细问题

### CR-001：Web 会话认证模型不成立，Docker 暴露后可被远程直接使用

严重级别：P0  
影响：未授权访问、远程控制爬取与下载、读取/修改本地媒体目录、触发 SSRF 或文件副作用。

证据：

- `app/web/rest_router.py:31-34` 的 `/api/session/bootstrap` 直接返回 `session_id` 和 `session_token`。
- `app/web/http_session.py:38-43` 只对 `POST/PUT/DELETE` 检查 Origin 和 `X-Ucrawl-Session-Token`。
- `app/web/http_session.py:46-54` 会给客户端设置会话和 token Cookie。
- `app/web/session_runtime.py:25-32` 对无 Origin 请求直接返回允许。
- `app/web/server.py:41-45` CORS 允许 `localhost`/`127.0.0.1` 任意端口并开启 credentials。
- `Dockerfile:23-30` 设置 `UCRAWL_HOST=0.0.0.0`。
- `docker-compose.yml:18-22` 将容器 8000 端口映射到宿主机，并设置 `UCRAWL_HOST: 0.0.0.0`。

风险说明：

当前 token 更接近 CSRF token，而不是认证凭证。任何能访问服务的客户端都可以先调用 bootstrap 获取 token，再调用需要 token 的 API。非浏览器客户端通常没有 Origin 头，`is_allowed_origin(None)` 又返回允许，因此 Docker/LAN 暴露场景下基本等同于无认证。

修复建议：

- 默认只绑定 `127.0.0.1`；如果设置 `0.0.0.0`，必须要求显式配置 `UCRAWL_AUTH_TOKEN`、账号密码或反向代理认证。
- `/api/session/bootstrap` 不应向未认证请求返回可操作 token。
- 区分认证 token 与 CSRF token：认证用于识别用户/部署权限，CSRF 仅用于浏览器防护。
- 无 Origin 请求在远程服务模式下不应直接放行。
- 启动时检测 `host=0.0.0.0` 且无认证配置时直接失败或至少强警告。
- 增加回归测试：无认证时不能在 `0.0.0.0`/Docker 模式调用写接口。

### CR-002：WebSocket 绕过 REST 目录授权与 `save_dir` 授权

严重级别：P0  
影响：任意目录扫描、切换保存目录、绕过下载保存目录限制、后续删除/重命名文件风险扩大。

证据：

- REST 路由侧有授权：`app/web/workflow_route_service.py:18-29` 对 `save_dir` 调用 `context.require_directory()`。
- REST 下载/爬取入口使用该授权：`app/web/workflow_route_service.py:31-36`、`app/web/workflow_route_service.py:45-50`。
- WebSocket 启动爬取直接调用 workflow：`app/web/ws_dispatcher.py:64-65`。
- WebSocket 扫描目录直接调用 controller：`app/web/ws_dispatcher.py:74-89`。
- WebSocket 切换目录直接调用 controller：`app/web/ws_dispatcher.py:91-100`。
- WebSocket 直链下载直接调用 workflow：`app/web/ws_dispatcher.py:158-159`。
- controller 的异步扫描/切目录自身没有再执行 `context.require_directory()`：`app/web/controller.py:587-624`、`app/web/controller.py:667-694`。

风险说明：

这是典型的多入口校验不一致。REST 入口看起来限制了 `save_dir`，但 WebSocket 入口没有复用同一授权层。只要攻击者拿到 WebSocket 会话，就可以要求后端扫描或切换到任意进程可访问目录，并可能影响后续下载、删除、重命名操作。

修复建议：

- 建立统一的 use-case/service 层，例如 `DirectoryUseCase`、`DownloadUseCase`、`CrawlUseCase`，REST/WS/CLI/GUI 都只能调用这一层。
- 目录授权必须在业务用例边界执行，而不是只放在某个 HTTP route wrapper。
- `async_scan_local_dir()`、`async_change_dir()` 等 controller 方法要么只接受已授权的 `AuthorizedPath` 类型，要么内部强制调用 `PathPolicy`。
- WebSocket 消息增加与 REST 等价的 schema 校验、权限校验和错误码。
- 增加回归测试：WS `scan_dir`、`change_dir`、`download.save_dir` 对未授权目录必须返回 403/错误事件。

### CR-003：直链下载缺少网络访问策略，存在 SSRF/任意响应落盘风险

严重级别：P0  
影响：内网探测、访问云元数据服务、读取本机/局域网 HTTP 服务、下载任意响应到本地目录。

证据：

- `app/web/workflow_download_request_service.py:46-66` 只验证 `url/source` 是字符串、平台存在，没有校验 scheme、host、DNS 解析结果和私网地址。
- `app/web/workflows.py:178-211` 直接构造 SDK 执行下载。
- `shared/sdk_runtime.py:273-341` 主要校验平台、配置与插件，未建立网络策略。
- `app/core/downloaders/base.py:143` 使用 `requests.get(url, ...)` 下载。
- `app/core/downloaders/ffmpeg.py:153-181` 对任意 URL 先执行 `requests.head()`，再进入 ffmpeg 下载路径。
- `app/core/downloaders/chunked.py:50`、`app/core/downloaders/chunked.py:99` 也会请求调用方传入的 URL。

风险说明：

当 Web API 可访问时，攻击者可以提交 `http://127.0.0.1:...`、`http://192.168.x.x/...`、`http://169.254.169.254/...` 等 URL，使服务器向本机、内网或云元数据地址发请求。若响应被保存为媒体文件或错误内容进入日志，还可能产生信息泄漏。

修复建议：

- 新增 `NetworkPolicy`：
  - 只允许 `http`/`https`。
  - 默认禁止 loopback、private、link-local、multicast、reserved IP。
  - DNS 解析后检查每个 A/AAAA 地址。
  - 禁止重定向到私网地址。
  - 每个平台定义允许域名或域名后缀。
- 对直链下载增加内容类型、最大响应体、最大重定向次数、单连接/总超时限制。
- ffmpeg/external downloader 前也必须执行同一 URL 策略，不能只保护 requests 路径。
- 增加回归测试：`localhost`、`127.0.0.1`、`10.0.0.0/8`、`172.16/12`、`192.168/16`、`169.254/16` URL 默认拒绝。

### CR-004：文件系统操作缺少统一最终路径授权

严重级别：P0/P1  
影响：创建任意目录、扫描敏感目录、通过符号链接读取授权目录外文件、删除或重命名非预期文件。

证据：

- `app/services/file_service.py:39-44` 的 `scan_directory()` 在目录不存在时会创建目录。扫描是读操作，但实际产生写副作用。
- `app/services/file_service.py:99-112` 的 `rename_media()` 使用 `os.path.join(save_dir, safe_name)`，但没有对 `old_path` 和 `new_path` 做最终真实路径 containment 校验。
- `app/services/file_service.py:114-119` 的 `delete_media()` 直接删除 `video.local_path`。
- `app/web/file_response_service.py:30-39` 只对 `os.path.dirname(path)` 调用目录授权，没有对文件自身的最终 `realpath` 做授权判断。授权目录内的符号链接可能指向目录外。
- `app/web/controller.py:709-726`、`app/web/controller.py:760-789` 调用删除/重命名时没有再次做目录授权。

风险说明：

当前授权粒度是“目录字符串”，而真正危险的是“最终落到哪个文件”。符号链接、路径大小写、路径归一化、网络盘、Windows junction、挂载点等都可能绕开简单 dirname/root 判断。扫描方法还会在任意传入路径不存在时创建目录，这会把读接口变成写接口。

修复建议：

- 新增统一 `PathPolicy`：
  - `resolve_existing_file(path)`：解析最终真实路径，拒绝不存在或不可访问文件。
  - `resolve_existing_dir(path)`：解析最终真实目录。
  - `assert_within_approved_roots(path)`：对最终 `realpath` 做 containment。
  - 对 Windows junction、符号链接做显式策略：默认拒绝或解析目标后授权。
- `scan_directory()` 不应创建目录；目录初始化应由启动配置或保存目录设置流程负责。
- 删除、重命名、文件响应必须验证最终文件路径在授权根内。
- 下载保存路径也必须通过 `PathPolicy`，不要让调用方传入裸字符串。
- 增加回归测试：授权目录内 symlink 指向外部文件时，文件响应、删除、重命名均被拒绝。

### CR-005：Cookie/凭据仍可能泄漏到前端传输、日志和明文文件

严重级别：P1  
影响：平台账号会话泄漏、账号被盗用、日志/接口响应中保留敏感 Cookie。

证据：

- `app/models/video_item.py:70-89` 的 `to_dict()` 会返回 `meta`。
- `app/models/video_item.py:91-106` 仅对 `cookie/cookies` 做 minimize，仍可能保留 `sessionid_ss`、`SESSDATA`、`a1` 等关键字段。
- `app/web/controller.py:867-869` Web 层直接委托 `VideoItem.to_dict()`。
- `app/core/lib/douyin/interface/template.py:533-536` 注释写着不打印 Cookie，但实际代码临时打开了完整 headers 打印。
- `app/services/auth_service.py:56-78` 将 Cookie JSON 明文写入文件，未见权限硬化或系统凭据库使用。

风险说明：

“最小化 Cookie”不等于“脱敏”。很多平台的少数字段本身就是完整会话凭据。只要这些字段进入 WebSocket/REST 响应、浏览器内存、前端日志、debug 日志或异常日志，就可能泄漏账号。

修复建议：

- `VideoItem.to_dict()` 默认不输出 Cookie。下载所需 Cookie 应保留在服务端凭据仓库中，用 `credential_ref` 引用。
- 日志层做 sink 级别的强制脱敏，不依赖每个调用点自觉过滤。
- 删除 `template.py` 中临时打印 Cookie 的代码，增加单测保证 `Cookie`/`Authorization` 不进入日志。
- Cookie 文件使用系统 keyring/DPAPI/Keychain/Secret Service；最低要求是文件权限 `0600` 和敏感目录隔离。
- API 响应增加敏感字段 denylist：`cookie`、`cookies`、`authorization`、`token`、`set-cookie`。

### CR-006：依赖与外部工具供应链风险较高

严重级别：P1  
影响：不可复现构建、供应链投毒、运行时版本漂移、安全漏洞难以及时定位。

证据：

- `requirements.txt` 和 `requirements-web.txt` 使用范围版本或未锁 patch 版本，没有 hash。
- `pyproject.toml` 也未提供 lockfile。
- `Dockerfile:1` 使用 `python:3.12-slim` 浮动标签。
- `Dockerfile:4-7` 默认使用外部镜像源和 pip 源，未校验包哈希。
- `Dockerfile:41` 安装 `ffmpeg curl tini gosu` 未固定版本。
- `Dockerfile:66` 与 `docker-compose.yml:32-35` 暴露并挂载 `/app/tools`。
- `app/core/downloaders/external.py` 会解析并执行外部工具路径，`app/utils/runtime_paths.py` 支持从工具根或 PATH 找二进制。

风险说明：

爬虫/下载器天然依赖网络、外部二进制和第三方库。缺少锁文件、哈希校验和 SBOM 时，线上问题难复现，安全漏洞难审计。可写的工具目录如果被污染，后续下载流程可能执行被替换的二进制。

修复建议：

- 使用 `uv.lock`、`poetry.lock` 或 `pip-tools` 生成带 hash 的锁文件。
- Docker 基础镜像 pin 到 digest，例如 `python@sha256:...`。
- 外部二进制纳入受控发布流程，记录版本、来源、sha256、签名校验。
- `/app/tools` 不应同时是可写数据卷和可执行搜索路径；至少拆分只读工具目录与可写下载目录。
- CI 增加 `pip-audit`、SBOM 生成、许可证扫描和镜像漏洞扫描。

### CR-007：本地 CORS/CSRF 模型过宽

严重级别：P1  
影响：本机恶意页面或其他本地 Web 服务可借浏览器访问 Ucrawl Web API。

证据：

- `app/web/server.py:41-45` 允许 `http://localhost:*`、`http://127.0.0.1:*` 且 `allow_credentials=True`。
- `app/web/session_runtime.py:25-32` 将无 Origin 请求放行。
- `app/web/ws_session_binding.py:32-38` WebSocket 只校验 Origin 和 Cookie token。
- `app/web/static/index.html:881-894` 前端 bootstrap 后缓存 token，并在后续请求携带。

风险说明：

浏览器 Cookie 是按 host 维度而不是按端口隔离。任意运行在 `localhost` 其他端口的页面，如果能满足 CORS 和 credentials 条件，就可能与本服务交互。WebSocket 侧只依赖 Cookie token 时，攻击者甚至不一定需要读取 token 才能建立跨端口 WS。

修复建议：

- 开发模式和生产模式分离 Origin 白名单。
- 默认只允许服务自身 origin，不允许任意 `localhost:*`。
- WebSocket handshake 要求显式一次性 token 或认证 header/subprotocol，不只依赖 Cookie。
- 使用 `SameSite=Strict`，并在需要跨源调试时通过显式配置打开。
- 加入 CSRF 回归测试：来自其他 localhost 端口的页面默认不能完成写操作或 WS 连接。

### CR-008：调试接口暴露在正式路由

严重级别：P2  
影响：被滥用触发内部测试逻辑、扩大攻击面、污染生产行为。

证据：

- `app/web/rest_router.py:75-77` 注册了 `/api/debug/trigger-select`。
- 项目文档 `app/web/INTERACTION_MAP.md` 多处记录该接口是测试端点。

修复建议：

- 通过 `UCRAWL_DEBUG_ROUTES=1` 显式开启调试路由。
- 默认生产/普通运行模式不注册任何 debug/test API。
- CI 增加断言：非 debug 模式 OpenAPI 中不能出现 `/api/debug/*`。

### CR-009：下载文件名去重不是原子操作，并发下可能覆盖或串写

严重级别：P2  
影响：并发下载同标题内容时文件互相覆盖、进度状态错乱、最终路径不可信。

证据：

- `app/core/download_manager.py:108-113` 在任务开始前通过 `_ensure_unique_path()` 计算路径。
- `app/core/download_manager.py:277-288` `_ensure_unique_path()` 只循环检查 `os.path.exists()`，没有原子创建或锁。
- 下载管理器支持并发任务，`max_concurrent` 大于 1 时风险实际存在。

风险说明：

两个同名任务几乎同时执行时，都可能在文件尚未创建前看到同一路径可用，最终写向同一个文件或互相覆盖。

修复建议：

- 在下载管理器内维护 per-directory filename reservation。
- 或使用 `os.open(..., O_CREAT | O_EXCL)`/临时文件原子占位。
- 下载先写入唯一临时文件，完成后原子 rename 到最终文件。
- 增加并发同标题下载测试，确保最终路径不同且内容不交叉。

### CR-010：超时/取消后后台线程或外部进程生命周期不够强约束

严重级别：P2  
影响：任务已返回失败但后台仍继续下载、占用网络/磁盘、状态回写错乱。

证据：

- `shared/sdk_runtime.py:496-519` 超时后调用 `dl_manager.stop_all()` 并返回超时状态。
- `app/core/download_manager_core.py:199-226` 停止 worker 后只等待有限时间；若未停止，会记录 timeout，但不能保证线程/进程全部结束。
- 外部工具路径有 kill 逻辑，但整体任务生命周期缺少统一的 hard-stop 合约。

修复建议：

- 引入显式 Job 模型：`queued/running/canceling/canceled/succeeded/failed/timed_out`。
- 每个 downloader 实现统一 `cancel()`，包括 requests、ffmpeg、外部进程。
- 超时返回前必须确认 terminal state，或返回 job id 并持续上报 canceling 状态。
- 对外部进程建立进程组，取消时 kill process group。

### CR-011：API 输入模型、大小限制和速率限制不足

严重级别：P2  
影响：大请求体、大目录扫描、过长 keyword/title/config 导致内存、CPU、日志或前端渲染压力。

证据：

- 多数 Web API 接收裸 `dict`，例如 `app/web/rest_router.py:64-89`。
- `app/web/directory_service.py:52-59` 只要求 `scan_limit > 0`，没有最大值。
- `app/services/file_service.py:46-65` 会先收集目录全部媒体项，再按 `max_scan_count` 截断。
- WebSocket 消息没有统一 schema、消息大小、频率和并发限制。

修复建议：

- 使用 Pydantic v2 模型定义所有 REST/WS 输入，设置 `max_length`、`ge/le`、枚举值和默认值。
- ASGI 层增加请求体最大值。
- 对 scan、download、crawl 设置 per-session rate limit 和并发上限。
- 大目录扫描改为流式/top-k 计数，避免先装载所有候选。

### CR-012：Web 配置变更缺少能力级授权，敏感路径可被间接修改

严重级别：P2  
影响：修改保存目录、Cookie 文件路径、代理、下载配置等，扩大后续文件和网络风险。

证据：

- `app/web/controller_config_service.py:32-49` 接收 section/key/value 并调用 `cfg.set()`。
- `app/config/settings.py:468-480` 做了 section/key/type 校验，但路径类配置缺少授权根限制。
- `app/utils/runtime_paths.py:136-141` 对用户文件路径支持绝对路径解析。
- `app/services/auth_service.py:37-43` `_validate_file_path()` 只拒绝包含 `..` 的路径，绝对路径仍可通过。

修复建议：

- 将“用户可改设置”和“内部敏感配置”拆分。
- Web 设置接口改为明确 allowlist，不提供任意 section/key 写入。
- Cookie 文件、auth 文件、工具目录、保存目录统一走 `PathPolicy`。
- 敏感配置变更要求更高权限或本机确认。

### CR-013：Origin 解析兼容性和策略边界较粗

严重级别：P3  
影响：IPv6 本机访问可能失败；无 Origin 默认允许与服务模式不匹配。

证据：

- `app/web/session_runtime.py:25-32` 通过字符串 split 提取 host，只允许 `localhost` 和 `127.0.0.1`。
- `::1` 不在白名单。

修复建议：

- 使用 `urllib.parse.urlparse()` 解析 Origin。
- 明确区分：
  - Desktop/local 模式：可接受无 Origin 的本机请求。
  - Server 模式：无 Origin 请求也必须认证。
- 加入 `::1` 和配置化白名单。

### CR-014：WebSocket 连接管理缺少锁、背压和大小限制

严重级别：P3  
影响：高频消息或断线重连时可能出现广播失败、列表并发修改、内存增长。

证据：

- `app/web/ws_transport.py:26-50` 使用 list 存储连接并在广播时遍历，connect/disconnect/broadcast 缺少锁。
- WebSocket 消息处理未见消息大小限制、心跳、发送队列容量控制。

修复建议：

- 使用 `dict[session_id, set[WebSocket]]` 和 `asyncio.Lock`。
- 每连接独立发送队列，设置最大长度，慢客户端丢弃或断开。
- 配置最大消息大小和心跳超时。

### CR-015：工程治理和编码工具链不足

严重级别：P3  
影响：质量波动、审计困难、贡献成本高。

证据：

- 当前环境缺少 `ruff`、`bandit`、`pip-audit`。
- 全量测试超过 2 分钟没有完成。
- 多个文件在 PowerShell `Get-Content` 输出中显示中文乱码，说明编码/终端/工具链未统一；即使源文件实际为 UTF-8，也需要项目层面固定编码策略。
- 仓库存在大量未跟踪/已修改文件，审查过程中未覆盖其历史来源。

修复建议：

- 标准化 `pyproject.toml`：ruff、mypy/pyright、pytest、coverage、bandit 配置。
- 所有源文件统一 UTF-8，增加 `.editorconfig`。
- 测试分层：unit、integration、slow、e2e，CI 默认跑快速集，夜间跑全量。
- 建立最小覆盖率门禁和关键安全回归测试。

## 5. Bug 与可用性问题补充

### 5.1 REST/WS 行为不一致会导致长期维护缺陷

REST 中部分流程已经抽出了 route service，但 WS 仍直接调用 controller/workflow。后续每修一个 REST 权限或校验，很容易忘记 WS。建议把 REST 和 WS 都改成薄传输层，所有状态修改都必须进入同一个 application service。

### 5.2 `scan_directory()` 的职责混杂

扫描方法目前同时负责“目录不存在时创建目录”和“扫描媒体”。这会让调用者难以判断一个方法是否安全。建议拆成：

- `ensure_download_directory(path)`：只在保存目录初始化时调用。
- `scan_existing_directory(path)`：只读，不创建。

### 5.3 文档中已有一些历史 bug 记录，但缺少可执行回归

`app/web/INTERACTION_MAP.md` 记录了大量交互和历史 bug，说明项目在快速迭代。但这些知识最好沉淀成测试，而不是只保留在大文档中。否则后续重构时很难自动发现退化。

## 6. 工业级架构调整方案

### 6.1 目标架构原则

建议采用“传输层薄、用例层集中、领域层纯、基础设施可替换”的结构：

```text
UI / CLI / SDK / REST / WebSocket
        |
        v
Application Use Cases
  - CrawlUseCase
  - DownloadUseCase
  - MediaLibraryUseCase
  - ConfigUseCase
  - AuthUseCase
        |
        v
Domain Model / Policies
  - VideoItem / DownloadJob / CrawlJob
  - PathPolicy / NetworkPolicy / SecretPolicy
  - PluginContract / Capability
        |
        v
Infrastructure
  - HTTP clients / downloaders / ffmpeg / filesystem
  - persistence / config store / secret store
  - websocket broadcaster / task queue
```

核心要求：

- REST、WS、CLI、GUI 不直接操作文件系统、下载器、配置对象。
- 所有路径、网络、凭据、插件权限都通过 Policy。
- 所有长任务都有 Job ID、状态机、取消语义和事件流。
- 所有外部输入都用类型化模型校验。

### 6.2 安全边界重构

优先新增以下策略对象：

| 策略 | 职责 |
|---|---|
| `AuthPolicy` | 判断当前部署模式、认证方式、会话权限 |
| `CsrfPolicy` | 浏览器跨站请求防护，不替代认证 |
| `PathPolicy` | 路径归一化、授权根、symlink/junction 策略、删除/重命名/响应授权 |
| `NetworkPolicy` | URL scheme、host allowlist、DNS/IP 私网拦截、redirect 检查 |
| `SecretPolicy` | Cookie/token 脱敏、存储、日志过滤 |
| `PluginPolicy` | 平台插件能力声明、允许域名、是否允许外部工具 |

落地顺序：

1. 先实现 `PathPolicy` 与 `NetworkPolicy`，接入 Web 下载和媒体库操作。
2. 再实现真实认证，修复 Docker 暴露面。
3. 最后把 Cookie 管理迁移到 SecretStore。

### 6.3 应用层用例收敛

建议新增 `app/application/`：

```text
app/application/
  auth_usecase.py
  crawl_usecase.py
  download_usecase.py
  media_library_usecase.py
  config_usecase.py
  session_context.py
```

每个用例只接收已经 schema 校验过的 command：

```text
StartCrawlCommand
DirectDownloadCommand
ScanDirectoryCommand
ChangeDirectoryCommand
DeleteMediaCommand
RenameMediaCommand
UpdateConfigCommand
```

REST 和 WS 的职责只剩：

1. 解析请求。
2. 认证当前 session/user。
3. 构造 command。
4. 调用 usecase。
5. 返回结果或订阅事件。

这样可以彻底避免 CR-002 这种入口绕过。

### 6.4 任务系统

爬取和下载都属于长任务，建议抽象统一 `Job`：

```text
Job
  id
  type: crawl | download | scan
  owner_session
  status: queued | running | canceling | canceled | succeeded | failed | timed_out
  progress
  created_at / started_at / finished_at
  cancellation_token
  artifacts
  error
```

能力：

- 任务状态可查询。
- WebSocket 只订阅任务事件。
- REST 可启动、取消、查询任务。
- SDK/CLI 可复用同一任务运行器。
- 下载器必须实现统一取消协议。

### 6.5 插件体系工业化

当前平台适配有插件雏形，但工业级需要明确契约：

- 插件 manifest：`id`、`name`、`version`、`supported_domains`、`capabilities`、`requires_cookies`、`external_tools`。
- 插件接口版本化：避免插件和核心代码同步修改。
- 插件测试套件：每个平台至少有 URL 解析、搜索 mock、下载 mock、cookie 过期处理测试。
- 插件网络访问必须声明 allowlist，由 `NetworkPolicy` 执行。
- 插件日志默认不能输出 headers/cookies。

### 6.6 配置与密钥管理

建议拆分：

```text
config/
  public_settings.toml     # UI 可改
  runtime_settings.toml    # 启动参数/部署配置
  secrets/                 # keyring 或加密引用，不直接明文暴露
```

Web UI 可改的设置必须通过 allowlist。敏感项如代理、Cookie 文件、工具路径、保存根目录，需要更强确认或仅允许本机/管理员修改。

### 6.7 可观测性

建议统一结构化日志：

- 每个请求/任务有 `trace_id`。
- 日志 sink 强制脱敏。
- WebSocket 事件也带 `trace_id/job_id`。
- 下载速度、失败原因、平台错误码、重试次数进入 metrics。
- 安全相关事件进入 audit log：登录、认证失败、路径拒绝、URL 拒绝、配置变更。

### 6.8 CI/CD 与质量门禁

建议 CI 至少包含：

```powershell
python -m compileall app cli entry shared ucrawl
ruff check .
ruff format --check .
pytest -q -m "not slow"
coverage run -m pytest -q -m "not slow"
coverage report --fail-under=80
bandit -r app shared cli entry ucrawl
pip-audit
python -m pip check
```

Docker/发布：

- 镜像 digest pin。
- 非 root 用户运行，当前 entrypoint 使用 `gosu ucrawl` 是好的方向，但建议 Dockerfile 也明确 `USER` 或在文档中解释 root entrypoint 仅用于 chown。
- rootfs 尽可能 read-only。
- 工具目录只读，数据目录单独挂载。
- 生成 SBOM 与镜像扫描报告。

## 7. 建议修复路线图

### 第 0 阶段：立即止血

目标：关闭最高风险暴露面。

- Docker 默认不要 `0.0.0.0` 无认证运行。
- 需要远程访问时必须设置 `UCRAWL_AUTH_TOKEN` 或登录密码。
- 移除或关闭 `/api/debug/trigger-select`。
- 删除 Douyin headers/Cookie 临时打印。
- WebSocket 的 `scan_dir`、`change_dir`、`download`、`start_crawl.save_dir` 立即补上和 REST 一致的 `context.require_directory()`。

### 第 1 阶段：统一安全策略

目标：让路径、网络、凭据不再散落各处。

- 实现 `PathPolicy`，接入 scan/delete/rename/file response/download save_dir。
- 实现 `NetworkPolicy`，接入 direct download、ffmpeg、chunked、平台下载器。
- `VideoItem.to_dict()` 默认去掉所有 cookie/token 类字段。
- Web API 使用 Pydantic request/response model。

### 第 2 阶段：收敛应用层架构

目标：消除 REST/WS/GUI/CLI 多套逻辑。

- 建立 `app/application` 用例层。
- REST/WS 只做传输适配。
- Controller 不直接承载权限和复杂业务。
- 引入统一 Job 模型和事件总线。

### 第 3 阶段：工程化与发布治理

目标：可复现、可审计、可持续交付。

- 建立锁文件和 hash 校验。
- 加入 ruff、bandit、pip-audit、mypy/pyright。
- 拆分 fast/slow/e2e 测试。
- 外部工具版本和 sha256 固化。
- 生成 SBOM，发布时附带安全扫描结果。

## 8. 推荐新增回归测试

优先新增以下测试：

1. 未认证情况下，`/api/session/bootstrap` 不能返回可操作 token。
2. `host=0.0.0.0` 且未配置认证时，服务启动失败。
3. WebSocket `scan_dir` 对未授权目录返回错误。
4. WebSocket `change_dir` 对未授权目录返回错误。
5. WebSocket `download.save_dir` 与 REST 行为一致，未授权目录拒绝。
6. 直链下载拒绝 `localhost`、`127.0.0.1`、私网、link-local、metadata IP。
7. 授权目录内 symlink 指向外部文件时，文件响应拒绝。
8. 删除/重命名 symlink 或授权根外文件时拒绝。
9. 并发同标题下载产生不同最终路径。
10. `VideoItem.to_dict()` 不输出任何 Cookie/token 类字段。
11. 日志中出现 `Cookie`、`Authorization`、`SESSDATA`、`sessionid` 时测试失败。
12. 非 debug 模式下 `/api/debug/*` 不注册。

## 9. 可接受风险与说明

- 本项目看起来首先面向本机桌面/个人使用场景，因此“localhost 信任模型”可以理解。但项目同时提供 Docker Web 模式，并默认 `0.0.0.0`，这会把个人工具风险提升为网络服务风险。
- 由于全量测试未在当前时间窗口内完成，报告中的测试结论只覆盖已执行的聚焦测试。
- 当前工作区存在大量已修改和未跟踪文件，本报告没有尝试回滚或清理任何已有改动。
- PowerShell 输出中文注释时出现乱码，可能是终端编码与文件编码不一致，不一定代表源文件损坏；但建议项目显式统一 UTF-8 工具链。

## 10. 结论

项目最需要优先处理的不是单点代码风格问题，而是“安全策略没有成为架构的一等公民”。一旦把认证、路径、网络、凭据、任务生命周期收敛成统一的策略和用例层，REST、WebSocket、CLI、GUI 四个入口就能共享同一套行为，后续功能迭代会安全很多，也更容易做自动化测试和工业化发布。

