# 公网网络边界工程约束：Playwright、HLS DNS 与平台 URL

> 本文记录项目中外部 URL 从输入、浏览器访问到 HLS 传输的统一安全边界。凡是由用户输入、站点返回值、重定向或页面脚本决定目标地址的代码，都必须遵守本文约束。

更新日期：2026-07-15

## 结论

公网访问不能只在入口做一次字符串检查。当前项目按三层边界处理：

| 层级 | 统一做法 | 防止的问题 |
| --- | --- | --- |
| 平台输入层 | 用解析后的 `hostname` 做精确域名或真实子域匹配 | `bilibili.com.attacker.example` 等伪子域绕过、登录入口跳到外域 |
| Playwright 浏览器层 | 在 `BrowserContext` 上安装共享守卫，并关闭额外脚本网络通道 | popup 首请求、子资源、WebSocket、Worker、Service Worker 绕过 |
| HLS 传输层 | 先解析并验证公网地址，再用 `CurlOpt.RESOLVE` 固定本次连接 | URL 校验后发生 DNS rebinding，连接落到内网地址 |

三层检查不能互相替代：合法平台域名仍需网络地址策略，浏览器 URL 路由也不等于传输层 DNS pinning。

## Playwright：守卫必须属于 BrowserContext

公网策略必须安装在 `BrowserContext`，并且必须在创建任何 `Page`、popup 或发起导航之前完成。只给单个 `Page` 安装 `route()` 不足以构成完整边界，因为 popup 的首次导航可能发生在页面级路由接管之前，而同一 context 中后续创建的页面也不会自动继承 page 级处理器。

项目统一入口是 `shared/playwright_network_guard.py` 中的 `install_public_network_guard()`。推荐调用顺序：

```python
context_kwargs["service_workers"] = "block"
context = browser.new_context(**context_kwargs)
install_public_network_guard(context, public_domain_policy)
page = context.new_page()
```

不得把上述顺序改成“先创建页面或导航，再补装守卫”。不得在某个平台内复制一套弱化版 URL 检查。

相关 Playwright 行为与 API 参考：

- [BrowserContext API](https://playwright.dev/python/docs/api/class-browsercontext)
- [WebSocketRoute API](https://playwright.dev/python/docs/api/class-websocketroute)

### 为什么必须使用 BrowserContext

`BrowserContext` 是一个浏览器会话内页面、popup、子资源和脚本初始化的共同所有者。把策略安装在 context 有三个直接收益：

1. 覆盖当前页面以及之后创建的所有页面。
2. 覆盖 popup 的首次导航；这是 `Page.route()` 无法可靠覆盖的关键窗口。
3. context 级 `add_init_script()` 会在页面脚本运行前生效，可统一关闭额外网络通道。

`BaseSpider._ensure_playwright_public_route()` 仍保留 Page fallback，只用于旧版 Playwright 或测试替身缺少部分 context 能力的情况。正常生产代码必须优先传入 context；fallback 只补齐 context 缺失的能力，不能反过来成为默认路径。

### 当前防护面

共享守卫按失败关闭原则处理以下通道：

| 通道 | 当前策略 | 原因 |
| --- | --- | --- |
| HTTP / HTTPS 导航与子资源 | context `route("**/*")` 逐请求调用 `DomainPolicyEngine.require_public_url()`；违规请求以 `blockedbyclient` 中止 | 阻止 loopback、私网、链路本地地址及不允许的 URL |
| popup 首次导航 | 由 context 路由统一接管 | page 级路由存在首次请求窗口 |
| WebSocket | `route_web_socket()` 做二次 URL 校验；页面初始化脚本同时禁用 `WebSocket` 构造器 | 避免 HTTP 路由之外的长连接绕过 |
| Worker / SharedWorker | 初始化脚本把构造器替换为抛出 `SecurityError` 的失败关闭实现 | Worker 可形成独立脚本与网络执行面 |
| Service Worker | 创建 context 时显式设置 `service_workers="block"` | Service Worker 接管请求后，路由层可能看不到真实网络访问 |
| `about:` / `blob:` / `data:` | HTTP 路由允许继续；脚本网络构造器仍受限制 | 保留页面本地资源能力，不把它们误判成公网 URL |

守卫使用 context/page 标记保证重复安装幂等。安装脚本或路由失败时必须抛出 `DomainPolicyViolation`，不得记录日志后继续无保护导航。

### 兼容性取舍

受公网策略保护的 context 当前禁用 WebSocket、Worker、SharedWorker 和 Service Worker。这会降低依赖这些能力的网站兼容性，但比允许页面脚本绕过 URL 策略更安全。

如果某个平台确实必须使用其中一种能力，不能直接删除初始化脚本或给单个平台加静默开关。应先完成独立威胁建模，提供等价的逐连接/逐请求校验，并补真实浏览器回归；在此之前保持失败关闭。

## curl_cffi HLS：校验后固定 DNS 结果

只调用 `DomainPolicyEngine.require_public_url()` 仍存在检查与使用时机差异：策略校验时域名可以解析到公网地址，`session.get()` 真正连接时再次解析却可能得到 loopback 或私网地址。

`app/core/downloaders/m3u8.py::_curl_cffi_session_response()` 的公网策略路径必须逐跳执行：

1. 调用 `resolve_public_addresses(current_url)`，同时完成 URL 校验并取得本次已验证的地址集合。
2. 调用 `hls_proxy.curl_resolve_options()` 生成 `CurlOpt.RESOLVE`，保留 URL 的真实端口。
3. IPv6 地址在 curl resolve 条目中使用方括号，IPv4 与 IPv6 可以同时固定。
4. 把 resolve 选项临时合并到当前 `Session.curl_options`，执行 `session.get(..., allow_redirects=False)`。
5. 在 `finally` 中恢复 Session 原有选项，避免本次主机固定污染下一跳或下一次请求。
6. 手动解析重定向，下一跳重新执行验证和 pinning；跨源跳转继续剥离 Cookie、Authorization、Host 和代理认证头。

当前 `curl_cffi` 版本的 `Session.get()` 不接受请求级 `curl_options`。不能为了代码看起来更局部而传入一个运行时不支持的参数；固定解析必须通过 Session 支持的选项完成。如果 Session 不暴露可安全合并的 `curl_options` 字典，公网策略路径必须失败关闭。

禁止退回以下写法：

```python
policy.require_public_url(url)
session.get(url)  # 实际连接会再次解析 DNS，未固定已验证地址
```

最低回归要求：

- 断言请求执行期间存在 `CurlOpt.RESOLVE`。
- 覆盖非默认端口，例如 `8443`。
- 同时覆盖 IPv4 和 IPv6 格式。
- 断言没有给 `Session.get()` 传入不兼容的请求级 `curl_options`。
- 成功、异常和重定向后都恢复原 Session 选项。
- 私网首跳和私网重定向在发起下一次请求前被拒绝。

对应测试入口是 `tests/test_downloaders.py` 和 `tests/test_m3u8_downloader_lifecycle.py`。

## 平台 URL：授权 hostname，不授权字符串片段

URL 提取、URL 归一化和主机授权是三个不同步骤。代码从分享文案中提取出一个看起来像 URL 的字符串后，仍必须通过 `urllib.parse.urlparse/urlsplit` 取得 `hostname`，再做授权判断。

### Bilibili

普通站点只接受：

```python
host == "bilibili.com" or host.endswith(".bilibili.com")
```

短链域名只接受项目声明列表中的精确 hostname，例如 `b23.tv`、`bili2233.cn`、`bili22.cn`。不要使用 `"bilibili.com" in netloc`、`netloc.endswith("bilibili.com")` 或对完整 URL 做子串判断，因为这些写法会错误接受：

- `bilibili.com.attacker.example`
- `notbilibili.com`
- `bilibili.com@attacker.example`

不在授权主机集合内的 URL 应按普通搜索词处理，不能进入 Bilibili 页面扫描或视频直取路径。

### Xiaohongshu

登录 bootstrap 入口只接受 `xiaohongshu.com`、`xhslink.com`、`xhslink.cn` 的精确域名或真实子域。输入是外域、伪子域或解析失败时，必须在创建登录页面前回退到 `HOME_URL`，不能把未授权地址交给带 Cookie 的登录 context。

短链跟随后得到的每一跳仍要经过 URL/公网策略；“初始短链域名合法”不代表重定向目标自动可信。

平台主机回归至少覆盖：

- 官方根域名和真实子域正常路由。
- 官方短链域名正常路由。
- `official-domain.attacker.example` 被拒绝。
- `notofficial-domain` 和 userinfo 混淆被拒绝。
- 小红书不可信登录入口回退 `HOME_URL`，可信入口保持原值。

对应测试入口是 `tests/test_spider_helpers.py` 和 `tests/test_xiaohongshu_integration.py`。

## 已知边界：Playwright DNS 二次解析

context 路由验证的是 URL 及策略解析结果，但 Chromium 在实际连接时仍可能再次解析主机名。因此，这套守卫不能被描述为已经彻底消除 DNS rebinding 的传输层 TOCTOU（检查与使用时机差异）。

当前项目已经对 `curl_cffi` HLS 路径使用 `CurlOpt.RESOLVE` 固定已验证地址；Playwright HTTP 传输若要达到同等级别，需要引入验证代理、浏览器级 IP pinning 或等价的传输层方案。未完成该方案前：

- 文档和 CR 结论必须明确保留这个残余风险。
- 不得把 URL 路由校验等同于连接地址固定。
- 不得为了“看起来已解决”而在证书、Cookie、重定向或 CORS 语义不完整的情况下自行代理 HTTPS。

## 接入要求

新增或修改外部 URL 路径时先判断它属于输入、浏览器或直接传输中的哪些层级；经过前一层不代表可以跳过后一层。

新增或修改 Playwright context 时按以下顺序检查：

1. 判断目标是否可能由外部输入、页面内容或重定向决定；若是，使用公网 `DomainPolicyEngine`。
2. 在 `browser.new_context()` 参数中加入 `service_workers="block"`。
3. context 创建后立即调用 `install_public_network_guard(context, policy)`。
4. 完成守卫安装后，才能应用其他 init script、创建 Page、恢复 Cookie 或导航。
5. 所有重定向、popup、子资源和备用浏览器路径必须复用同一策略。
6. 安装失败、策略能力缺失或 URL 校验失败时必须停止该路径。

当前生产接入点包括：

- `app/spiders/base.py`：Spider 通用 Playwright 页面。
- `app/spiders/douyin/spider.py`：抖音登录子进程 context。
- `app/core/downloaders/m3u8.py`：HLS Playwright 兜底 context。
- `app/core/downloaders/m3u8.py`：curl_cffi HLS 逐跳验证与 DNS pinning。
- `app/spiders/bilibili/input_router.py`：Bilibili 输入 hostname 授权。
- `app/spiders/xiaohongshu/spider.py`：小红书登录入口 hostname 授权与安全回退。

## 回归测试要求

安全回归不能只检查源码字符串或注释，必须验证行为。最低覆盖包括：

- 私网 HTTP 子资源被 abort，且不会调用 `continue_()`。
- context 路由在 Page 创建前安装，popup 首次私网请求无法到达真实 loopback TCP listener。
- 私网 WebSocket 不会连接服务器。
- `WebSocket`、`Worker`、`SharedWorker` 构造器在真实 Chromium 中抛出 `SecurityError`。
- 所有受保护 context 都显式设置 `service_workers="block"`。
- 守卫重复安装不会注册重复 handler。
- 旧版测试替身缺少 context 能力时，Page fallback 只补缺失能力。

对应测试入口：

- `tests/test_spider_base.py`
- `tests/test_m3u8_downloader_lifecycle.py`
- `tests/test_spider_helpers.py`
- `tests/test_xiaohongshu_integration.py`
- `tests/test_downloaders.py`
- `tests/web_browser_cases/network_guard.py`

## CR 检查清单

- [ ] 守卫是否安装在 `BrowserContext`，而不是只安装在 Page？
- [ ] 是否在任何 Page、popup 或导航创建前完成安装？
- [ ] 是否显式阻止 Service Worker？
- [ ] WebSocket、Worker 和 SharedWorker 是否仍保持失败关闭，或已有经审查的等价保护？
- [ ] 新增浏览器备用路径是否复用共享守卫？
- [ ] 是否包含真实 popup 首请求和脚本网络通道回归？
- [ ] 结论是否诚实区分 URL 校验与传输层 DNS pinning？
- [ ] curl_cffi 公网请求是否把已验证地址固定到真实连接，并在请求后恢复 Session 选项？
- [ ] 自定义端口和 IPv6 是否包含在 DNS pinning 回归中？
- [ ] 平台域名是否基于解析后的 hostname 做精确域名/真实子域判断，而不是字符串包含？
- [ ] 带登录 Cookie 的浏览器入口遇到外域或伪子域时是否在创建页面前安全回退？
