# 快手短链 curl DNS 固定设计

## 背景与根因

快手分享短链先由现有 `DomainPolicyEngine` 在 Python 侧验证域名并解析出公网地址，随后却把原始 URL 交给 `curl_cffi`。libcurl 会再次使用系统 DNS 独立解析，因此在系统解析异常时，请求会在首个 HTTP 跳转前以 `Could not resolve host` 失败。验证过的公网 DNS 结果没有绑定到真正发起连接的传输层，安全校验和网络连接之间也存在 DNS 重绑定窗口。

对失败样本 `https://www.kuaishou.com/f/X-4MrKFUMNjVt1RA` 的验证表明：把策略引擎返回的公网地址通过 `CurlOpt.RESOLVE` 交给 curl 后，短链能够完成 302 跳转并取得包含 `window.__APOLLO_STATE__` 的详情页 HTML。快手当前会对匿名响应返回媒体字段为空的 Apollo 骨架；同一路径按浏览器规则携带项目已有登录态后，现有 Apollo 解析器可直接提取标题与视频地址，无需启动浏览器兜底。

## 目标

- 让快手短链的 DNS 公网校验结果与 `curl_cffi` 的实际连接保持一致。
- 每个重定向跳转都重新验证目标 URL、解析公网地址并生成独立的 DNS 固定项。
- 支持默认端口、自定义端口、IPv4 和 IPv6。
- DNS 校验超时、没有可固定的公网地址或无法构造固定项时失败关闭，不发起 curl 请求。
- 配置了由代理端解析目标域名的 HTTP/SOCKS 代理时，短链 HTTP 快路失败关闭并进入现有浏览器兜底；不得绕过用户代理，也不得宣称 `CurlOpt.RESOLVE` 能约束代理端 DNS。
- 保留现有 15 秒总预算、最多 5 次重定向、2 MiB 响应体上限、允许域名策略、响应释放和浏览器兜底语义。
- 短链 HTTP 快路只读现有 Playwright 登录态，并在每一跳按目标 URL 重新筛选 Cookie；不得跨域、跨路径或把无作用域 Cookie 发到网络。
- HTTP 路径成功取得详情 HTML 后，继续复用现有响应缓存与 Apollo 解析器，避免不必要的浏览器启动。

## 范围与非目标

本次只修改快手短链传输路径、通用 URL Cookie 筛选边界及其测试，不重构全局网络工具，不迁移 m3u8/HLS 调用点，也不改变浏览器会话、Cookie 文件格式、登录态写入/替换规则、等待时间或重试策略。HTTP 快路仅读取任务开始时的登录态快照；浏览器兜底仍重新从磁盘加载最新状态。

浏览器兜底仍用于真实的 HTTP/内容解析失败；DNS 固定成功且直连解析成功时不应进入兜底。不会通过恢复 `reload`、增加睡眠或扩大超时掩盖问题。

## 方案

在快手 `share_runtime` 内增加小范围 DNS 固定构造逻辑，并让现有受限请求准备阶段返回当前跳转唯一的 ASCII-IDNA 传输 URL 与 curl 选项：

1. 先执行现有允许域名与公网目标策略检查。
2. 校验 scheme、主机、凭据和 1 至 65535 端口，将主机转为 ASCII IDNA；保留 trailing dot、显式/默认端口语义、路径、查询和片段。规范化失败统一包装为 `DomainPolicyViolation`，保留原短链并进入浏览器兜底。
3. 在现有有界后台校验任务、信号量和总截止时间内，把同一个 ASCII 传输 URL 交给 `DomainPolicyEngine.resolve_public_addresses()` 获取已验证的公网地址。
4. 从传输 URL 计算主机与端口。显式端口优先；否则 HTTPS 使用 443，HTTP 使用 80。
5. 将 IPv6 地址用方括号包裹，保留 IPv4 原样，构造单条 `host:port:address[,address...]` 的 `CurlOpt.RESOLVE` 配置；同一 request-scoped `curl_options` 必须设置 `CurlOpt.PROXY: ""`，禁止 libcurl 读取环境代理。
6. 仅当输入是快手短链时，在展开前只读一次现有 Playwright storage state；不写入浏览器持久化使用的 `_loaded_storage_state`。
7. 对当前 ASCII 传输 URL 按浏览器 domain、path、Secure 和 expiry 规则严格筛选 Cookie；拒绝 flat dict、缺少 domain/path、非布尔 Secure、非法过期值以及含 curl 分隔符或控制字符的项。仅缺失 expiry 字段或数值 `-1` 表示 session，显式 `0`、空值、其他负值和非有限值均失败关闭。
8. 只有成功生成固定项后才把同一个 ASCII 传输 URL及当前跳 Cookie 交给 `curl_cffi.get()`；不传无效的 None proxy mapping，仍禁止 curl 自动跟随重定向。
9. 对每个 `Location` 先按现有规则规范化并验证，再回到步骤 1，为新 URL/主机重新规范化、解析、固定并重新筛选 Cookie。
10. 最终详情响应继续进入现有有界内容回调与缓存；后续解析消费同一份 HTML。响应缓存不保存 Cookie 或 storage state。

```text
当前 URL
  -> 允许域名检查
  -> ASCII IDNA 传输 URL（保留 trailing dot/端口/路径/查询/片段）
  -> 有界公网 DNS 解析
  -> CurlOpt.RESOLVE 固定已验证地址 + CurlOpt.PROXY="" 禁用环境代理
  -> 按当前跳 URL 严格筛选已保存 Cookie
  -> curl_cffi 单跳请求（不自动重定向）
  -> Location 校验后逐跳重复 / 最终 HTML 缓存
  -> Apollo 直连解析
  -> 仅在真实 HTTP 或内容失败时浏览器兜底
```

## 安全与错误处理

- 固定地址只能来自 `DomainPolicyEngine.resolve_public_addresses()`；不接受页面、响应头、用户参数或未经验证的 DNS 地址。
- 策略拒绝、解析超时、地址为空、主机/端口无效或固定项构造失败时，当前跳转失败关闭，且不得调用 curl。
- 显式端口必须在 1 至 65535 之间；`:0` 不得回退成协议默认端口，否则固定项可能与实际连接端口不一致。
- 每次跳转均重新解析和固定，不能沿用上一主机的地址，也不能让 libcurl 对新主机自行解析。
- 策略解析和 curl 请求必须接收逐字相同的 ASCII-IDNA 传输 URL；Unicode 主机、trailing dot 和显式端口不得导致 RESOLVE key 与实际连接主机不一致。
- 直连短链请求必须在 request-scoped `curl_options` 中显式设置 `CurlOpt.PROXY: ""`；`{"http": None, "https": None, "all": None}` 不能作为禁用 libcurl 环境代理的安全边界。
- IPv6 固定项使用方括号，避免地址中的冒号与 `host:port` 字段冲突。
- 拒绝所有带 scope ID/zone 的 IPv6 固定地址；不得把 scope 文本拼入 `CurlOpt.RESOLVE`，避免分隔符注入额外地址。
- Cookie 的 `/f` 路径只能匹配 `/f` 与 `/f/...`，不得前缀误配 `/foobar`；无 domain/path 的兼容 Cookie 只保留给旧调用，安全敏感快路必须启用严格作用域。
- 每个重定向跳均重新筛选 Cookie；`.kuaishou.com` 与 `.chenzhongtech.com` 的登录态不得相互泄漏，Cookie 值不得进入日志、响应缓存或设计诊断输出。
- 请求与 DNS 校验共同消耗现有 15 秒总预算；不新增独立、可叠加的超时窗口。
- 重定向、异常和内容中止路径继续关闭响应，避免连接泄漏。
- 日志只记录阶段和失败类型，不记录 Cookie、签名或其他敏感值。

## 测试契约

按 TDD 先增加失败测试，再实现最小改动：

- 公网策略返回地址时，首跳必须携带 `curl_options[CurlOpt.RESOLVE]`。
- IPv4、IPv6、自定义端口和默认 HTTP/HTTPS 端口的格式正确。
- 重定向到不同主机或端口时，每一跳重新解析并生成新的固定项。
- mock 逐跳测试断言策略解析与 curl 收到完全相同的 ASCII-IDNA URL，并断言每跳 `CurlOpt.PROXY == ""`。
- 受控真实 curl 测试使用 Unicode/trailing-dot 平台子域、loopback RESOLVE 目标和环境代理 trap；必须到达目标服务器且不得到达代理 trap。
- 受控真实 curl 服务端必须实际观察到 URL 作用域内的登录 Cookie；mock 逐跳测试同时证明 Kuaishou 与 ChenZhongTech Cookie 不跨域、path/expiry/控制字符规则生效。
- 过长或无效 IDNA label 不得逃出 `KuaishouSpider.run()`；curl 不调用、原短链保留并执行一次分享浏览器兜底。
- DNS 无结果、超时或固定项无法构造时失败关闭，`curl_cffi.get()` 不得被调用。
- 配置远端解析代理或显式 `:0` 端口时失败关闭，`curl_cffi.get()` 不得被调用。
- 成功取得详情 HTML 后，现有响应缓存和 Apollo 解析器可提取媒体，且不启动 Playwright 浏览器。
- 保持既有总预算、后台校验闸门、重定向上限、响应体上限、403/5xx 分类和响应清理测试通过；第 6 次重定向必须失败并关闭全部已取得响应。

## 验收标准

- 失败样本短链在可用公网解析结果与有效本地登录态下通过 HTTP 直连得到详情页并完成媒体解析；验收输出只记录作品 ID 与解析布尔值，不输出 Cookie 或签名媒体 URL。
- 系统 DNS 异常不再导致 libcurl 忽略已验证的解析结果。
- 所有受影响的快手单元测试、网络安全测试及测试套件分类契约通过。
- 改动只包含快手短链实现、针对性测试和必要文档，不混入工作区其他未提交修改。
