# 全项目 CR 紧急修复设计

## 背景

本轮 CR 覆盖自当前 `main` 基线到工作区未提交内容的全部生产代码、测试、CI 与发布路径。审查已经完成首轮静态检查、定向复现和非浏览器全测，确认问题集中在五条边界：工具执行能力、公网请求与凭据、下载恢复完整性、Web 会话协议、进程生命周期与发布门禁。

当前工作区包含一组尚未提交的工具箱实现以及版本、文档和 CI 调整。本轮不丢弃、不覆盖这些改动，而是把它们当作待验收实现：先用测试固定正确契约，再做最小修复。所有改动按风险域分批提交并推送；每批只暂存该批文件，不夹带其他未提交内容。

版本回退行为不在修复范围内。它是为热更新保留验证窗口的明确产品决策，不得在本轮以“安全修复”名义移除。

## 目标

- 公网调用面不能借由代理、重定向、DNS 重绑定、浏览器上下文、HLS 本地代理或机器凭据访问非授权目标。
- 下载恢复账本、临时工作区和媒体释放请求在多任务、多线程、多进程下保持身份唯一、所有权明确和可确认交付。
- 工具声明的权限、来源、破坏性和依赖在宿主执行层真正强制，GUI、Web、CLI、SDK 的行为和生命周期一致。
- Web 每个连接只有一个写入者，增量版本只在成功写出后推进，断线、重连、BFCache 与 shutdown 不产生旧事件穿透。
- 队列、日志、缓存、stderr、重试、定时器和历史持久化都有明确容量上限及过载语义。
- CI 对真实生产包、测试分类、`ucrawl` 公共 SDK 和 Windows 交付物形成可执行门禁。

## 非目标

- 不重写已有爬虫、下载器或 UI 框架。
- 不改变用户明确要求的热更新回退验证窗口。
- 不顺手迁移无关文件，不批量格式化整个仓库，不清理用户的其他未提交改动。
- 不把“增加白名单”“延长超时”“增加 sleep”“吞掉异常”作为根因修复。

## 全局验收不变量

### 1. 身份和所有权

- 任何可并发的下载运行都使用不可复用的 `task_run_id`；`video_id` 仅是业务标识，不能作为运行实例主键。
- 可删除资源必须同时满足：调用者具备能力、资源属于调用者、资源没有有效 lease、状态已终止、删除请求可审计。
- Web 会话、工具运行、媒体释放和下载恢复记录均保存不可由客户端伪造的 owner/generation。

### 2. 公网和凭据

- URL 校验必须使用解析后的 scheme、ASCII host、有效端口和逐跳目标；不得使用子串判断。
- 公网 DNS 策略返回的地址必须绑定到实际连接；每次重定向重新校验和固定。
- 受保护的直连请求显式禁用环境代理；子进程只接收允许的最小环境。
- Cookie、Authorization、代理凭据和签名查询参数只发往其精确作用域，默认不进入日志、状态、历史或公共 DTO。
- public execution profile 默认不读取机器级认证、不启用 caller-controlled proxy、不加载外部工具插件。

### 3. 状态和交付

- 状态机显式区分 idle、queued、running、cancelling、succeeded、failed、cancelled、disabled；不得用展示文本代替状态。
- shutdown 必须把所有已接受任务推进到终态或明确移交；不能留下永久 queued/running 记录。
- 持久化采用原子替换或事务，并有跨进程协调；最后写入者不能覆盖其他进程的新数据。
- 失败批次只有在持久化成功后才能从内存移除；失败写入必须重新排队或保留可重试状态。

### 4. 容量和背压

- 每个入站队列、执行队列、出站队列、日志尾部、参数/result DTO、缓存、pending 集合和重试集合都有全局及必要的每 owner 上限。
- 容量耗尽时返回明确、可测试的过载错误；关键终态允许保留专用容量，但不能绕过 owner 和敏感字段投影。
- UI 只消费节流后的 section delta，服务持有数据和副作用，widget 只渲染；刷新不能重建整页或阻塞事件循环。

### 5. 测试和提交

- 每个行为修复先增加能在旧实现上失败的测试，记录 RED 原因，再做最小实现并得到 GREEN。
- 测试文件必须位于项目测试分类规范允许的 suite root；不得通过追加白名单绕过分类。
- 每批运行定向测试、架构契约、静态检查、`git diff --check` 和 secret scan；最后再运行完整测试矩阵。
- 每个 commit 只包含一个可解释的风险域，并在 push 前检查 staged diff。

## 方案一：工具执行运行时

### 宿主强制的执行配置

在 `shared/execution_profile.py` 建立全项目唯一、不可由插件构造的 `ExecutionProfile`。固定字段为 `host_surface`、`owner_id`、`allow_machine_credentials`、`allow_caller_proxy`、`require_public_network`、`allow_tool_execution`、`tool_permissions`、`approved_roots` 和 `allow_external_plugins`；队列/输出预算由使用它的有界服务配置。网络层、工具层、GUI、Web、CLI 和 SDK 只能消费这一类型及 `local_execution_profile()` / `public_web_profile()` 工厂；不得各自定义同名、相似 profile 或另一套常量。

工具 manifest 的静态声明由宿主生成的 `ToolRequirements` 解释。对 `download_residue` 这类参数会改变风险的工具，宿主在验证和执行前调用纯函数 `requirements_for(parameters)`：diagnose 需要只读 ledger/目录能力，cleanup 额外需要写入、删除和 destructive grant。插件返回的是需求，最终授权仍由宿主计算，插件不能自行授予能力。

Registry 为每个条目附加宿主生成的 provenance；插件 manifest 只是需求声明，不是授权。

执行顺序固定为：查找条目 -> 校验 provenance -> 计算 manifest requirements 与 profile grants 的交集 -> 校验参数和路径 -> 容量准入 -> 创建 owner-scoped record -> 执行。`approved_roots` 为空时对文件权限 fail closed。

GUI 使用 local-interactive profile；CLI 和 SDK 使用显式 local profile；Web public profile 第一阶段只展示诊断清单而不执行本地文件、网络、子进程或破坏性工具。只有单独完成身份、owner 和 DTO 契约后，Web 才能逐项开放安全工具。

### 运行和历史

Runner 在提交前执行全局和每 owner 容量检查。取消、查询、事件和清空历史均按 owner 过滤。shutdown 对尚未开始的 future 注册完成回调并推进为 cancelled；已经运行的任务收到 token，等待有界 quiescence。

持久化只保存正向投影后的公共字段，不保存原始参数。递归投影必须处理嵌套 token/cookie/password、URL userinfo、代理 URL、CloudFront/S3 签名查询和插件 result/progress。历史加载在公开 API 可用前完成，顺序统一为 newest-first。

CLI `run` 默认同步等待并按最终状态返回退出码；在没有单一 daemon/IPC 前，不宣传跨进程 cancel。SDK/CLI 的 close/finally 必须关闭实际拥有的 runner。

`download_residue` 的诊断和清理都先授权 ledger 路径；active/leased 行和工作区永远不进入删除候选。清理采用先诊断、生成 plan、再次验证 lease、再提交删除的两阶段流程。

## 方案二：公网请求和本地 HLS broker

### 传输约束

所有 public 直连都使用同一个安全请求准备器：规范化 URL、ASCII IDNA host、尾点、有效端口、host allowlist、公网解析、实际连接 pin、逐跳重定向、响应大小和总时限。`curl_cffi` 的每次请求使用独立 `curl_options` 或隔离 handle 设置 `CurlOpt.RESOLVE` 和 `CurlOpt.PROXY: ""`，不能通过“修改共享 session 后再恢复”实现；IPv6 RESOLVE 地址必须使用方括号。FFmpeg 和 HLS helper 使用去除 proxy/credential 环境变量的最小环境。

Playwright 防护继续采用 BrowserContext 路由以覆盖 popup 首请求；context 创建后立即安装路由和 WebSocket/Worker/SharedWorker/ServiceWorker 限制，在任何 navigation 之前完成。浏览器 HTTP(S) 通过每浏览器实例、带随机认证的 loopback CONNECT/forward proxy：代理逐个 CONNECT/请求规范化 host、解析公网地址并直接连接已验证 IP，且不读取环境上游代理。TLS 仍由 Chromium 与目标端到端协商，Cookie jar、`Set-Cookie`、导航、CSP 和页面请求语义继续由 BrowserContext 管理。不能安全固定或不支持的流量 fail closed；不得用不完整的 curl fulfill 替代浏览器传输。

### HLS capability

本地 broker 不再接受裸 base64 任意 URL。每个任务生成随机密钥或不可伪造 capability，token 至少覆盖 task id、目标 canonical URL、过期时间和用途。broker 只允许 manifest 中已验证的 playlist/segment/key 成员，跳转后重新校验成员和 host。

Cookie/Authorization 只有目标 host 与 credential policy 同时允许时才附加；跨 host 跳转剥离。响应不使用 wildcard CORS，只允许本地播放器需要的精确 origin 或完全不返回 CORS 头。

### 公共数据投影

`/api/search`、frontend state/delta、WebSocket bootstrap 和日志下载都使用独立 allowlist DTO：资源用 server-side handle；路径用 basename 或批准根相对路径；凭据仅暴露 configured 布尔值；URL 默认只暴露 host、稳定 id 或经确认安全的展示链接。

日志按 session/owner 分区。命令、Cookie、Authorization、代理 userinfo、签名 query 值不写入日志；诊断只记录阶段、host、path hash 和 query key 名称。

## 方案三：下载恢复与生命周期

Recovery schema 以 `task_run_id` 为主键，并为 workspace、media output、failed record 和 release request 保存 owner、不可伪造的 `instance_token`、PID、进程 start token、lease heartbeat、state、timestamps。lease 的 acquire、renew 和 release 均以 instance token 做 compare-and-swap，另一个同 PID 或同 owner 文本的进程不能抢占或续租。进程启动清理只回收 lease 已过期且通过 PID/start-token 二次确认 owner 已死亡的资源；cleanup claim 本身有 claimant instance token、TTL 和 CAS heartbeat。清理每个破坏性阶段前再次确认 claim 未过期，慢 cleaner 一旦失去 claim 必须停止并回滚；claim 仅在 claimant 死亡或确认过期后回收。不能按后缀或 `video_id` 扫描删除。

暂停和取消以运行实例为目标；按 `video_id` 的兼容入口必须检测歧义并拒绝批量误杀。跨进程媒体释放使用 append-safe 队列或 SQLite 表，每条请求有 request id、owner、状态和 ack；调用方等到自己的 ack，而不是依赖固定 sleep。

断点续传只有在 strong ETag/Last-Modified/长度等 validator 匹配并带 `If-Range` 时才能 append；缺少或变化时丢弃旧 partial，从零开始。FailedRecordStore shutdown 先停止接收，再 drain，写失败保留/重排，最终明确返回是否持久化完成。

GUI、Web、SDK、CLI 的 stop/close 采用同一顺序：停止接收 -> 发取消 -> 等待有界 quiescence -> flush 持久化 -> 释放进程/上下文 -> 标记 closed。超时返回未停组件清单，不提前销毁其依赖。

元数据 timer、pending、cache、retry 与 FFmpeg stderr 采用有界结构。timer 启动失败不能留下幽灵 pending；播放位置用事务/锁/原子替换合并更新，cleanup 前做最终 flush。

## 方案四：Web 会话和增量协议

每个已鉴权连接创建独立 connection generation、lease 和单写 outbox。REST/WS handler 只投递消息，不直接调用 socket send。连接在 pre-bootstrap 阶段不进入 active/broadcast registry；完整 snapshot 先进入同一 outbox，再在持锁条件下原子切换为 active，因此任何 live event 必须排在 bootstrap 后，且不会与 sender 并发写。

服务端维护 `last_written_version`，只在 send 成功后推进；没有客户端 ACK 时不得把它命名为 acknowledged version。只要存在尚未写出的 delta，就不能基于它继续生成链式 delta。需要 coalesce 时必须以 `last_written_version` 和当前 authoritative state 重算一个覆盖全部变化的 superseding delta；若不能证明覆盖完整，则丢弃 pending delta 并排入完整 snapshot。断线或 generation 结束时关闭 bridge、取消 producer、清空未写消息，旧 generation 不能写入新连接。

SessionRegistry 的 acquire/dispose 使用异步容量门或线程外执行，不在事件循环中阻塞 semaphore。创建或驱逐前对 running、queued 和 deferred disposal 的总容量做准入；容量耗尽时保留仍可寻址的 controller 并返回明确 overload，不能先从 lookup 删除再把唯一所有权交给可能已满的 deferred queue。WS 在鉴权成功和 bootstrap 安装完成前不分配昂贵浏览器/会话上下文，也不标记 active。

浏览器 `pagehide` 若 persisted 只暂停传输，不永久 dispose；`pageshow` 恢复并重新 bootstrap。普通 unload 才释放页面 lease。前端对 stale generation 和非连续版本 fail closed，触发一次有界 resync。

## 方案五：CI 与发布门禁

- 把 `ucrawl/**` 纳入 compile、Ruff、Bandit 和 coverage 的生产代码集合。
- Docker workflow 的 path filters 覆盖所有 COPY 输入：`ucrawl/**`、入口文件、README、图标和构建脚本。
- Windows job 真实构建 portable 与 installer，并对版本身份、入口启动、关键资源和卸载元数据做 smoke；不能只测试打包脚本 mock。
- 工具箱新增测试迁移到 canonical suite，并更新分类规则/文档；不追加逐文件白名单。
- Web CSS/JS 加载顺序、文件预算和公共边界由架构测试约束。超过预算时按职责拆分，不单纯抬高预算。
- 版本回退行为作为产品排除项写入验收说明；CI 只验证其身份一致性与签名，不改变策略，也不增加仅匹配文档措辞的伪行为测试。

## 分批提交与依赖顺序

1. 设计与计划：只新增本目录文档。
2. 执行配置 foundation：先独立建立 `shared/execution_profile.py` 的唯一类型、工厂和越权拒绝测试，工具与公网计划只消费它。
3. 工具箱测试分类和安全执行闭环：消除已合入工具箱的数据破坏与 CI blocker。
4. 公网传输 P0：环境代理、HLS capability、Douyin URL 校验。
5. Web 公共边界：cookie/proxy、DTO、日志、WS/CORS，复用 foundation profile。
6. 下载恢复：task_run_id、lease、账本、resume、释放 ack。
7. Web 会话协议：single-writer outbox、版本推进、generation、BFCache。
8. 生命周期和容量：SDK/CLI/GUI/Web stop、metadata/playback/stderr。
9. CI 与发布：生产包覆盖、Docker filters、Windows 实产物。
10. 全量回归与最终 CR：只修复由以上批次引入或暴露的回归。

前一批只有在定向测试、架构门禁和 staged diff 审核通过后才 push。后一批不得依赖未推送的隐含工作区状态。

## 最终验收

- P0/P1 复现用例全部由失败转为通过，并保留为回归测试。
- 完整非浏览器测试、浏览器契约、架构/安全/发布测试和静态检查通过。
- portable 与 installer 在干净 Windows 环境完成 smoke，构建身份与发布清单一致。
- secret scan、依赖审计和 staged diff 检查通过；已知第三方/环境问题单独列证据，不以跳过掩盖。
- 最终报告逐项对应 finding、修复 commit、测试证据和剩余风险；版本回退明确标注为用户批准的排除项。
