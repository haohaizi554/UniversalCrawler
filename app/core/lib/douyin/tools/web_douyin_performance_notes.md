# Web 抖音启动性能排障说明

> 更新时间：2026-06-08
> 适用目录：`app/core/lib/douyin/tools`

## 背景

在一次 Web 与 GUI 的对比排查中，发现同一条抖音链接在 Web 端首个条目出现时间明显慢于 GUI 端。
这次问题不是前端渲染或 WebSocket 广播造成的，而是抖音参数初始化链路本身被放大。

## 最终根因

根因分成两层：

1. `Parameter.update_params()` 在启动关键路径上做了不必要的远程参数刷新。
2. `Parameter.__init__()` 在无代理场景下仍然同步创建 `httpx` transport，并且顺手初始化了当前任务并不会使用的 `client_tiktok`。

运行时证据表明：

- `msToken` / `ttwid` 获取阶段曾经重复走远程链路。
- `phase_client` 是后续最大的剩余慢点。
- Windows 环境下 `httpx.AsyncClient()` 默认会做环境探测，`trust_env=True` 比 `trust_env=False` 明显更慢。

## 本次修复

### 1. 参数刷新降级为“本地优先”

位置：`parameter.py`

- 优先复用 cookie 中已有的 `msToken` / `ttwid`
- 优先复用 API 缓存中的 `msToken`
- 只有本地和缓存都缺失时，才允许走远程刷新
- 远程刷新超时被限制为快速失败，避免长期阻塞启动链

### 2. 无代理时不再强制创建 transport

位置：`session.py`

- `create_client()` 仅在显式配置 `proxy` 时才创建 `AsyncHTTPTransport`
- `request_params()` 仅在显式配置 `proxy` 时才创建 `HTTPTransport`
- 无代理场景直接使用 `httpx` 默认客户端

### 3. 默认关闭环境代理探测

位置：`session.py`

- `create_client()` 默认使用 `trust_env=False`
- `request_params()` 默认使用 `trust_env=False`

这样可以避免 Windows 上由于系统代理、环境变量或证书链探测导致的额外初始化耗时。

### 4. 只初始化当前平台所需客户端

位置：`parameter.py`

- 抖音任务只创建 `self.client`
- 仅在 `tiktok_platform=True` 时才创建 `self.client_tiktok`
- `close_client()` / `set_proxy()` 兼容客户端为空的情况

## 经验结论

后续在这个目录继续演进时，优先遵守下面几条：

- 不要把“可失败、可降级、可缓存”的远程参数刷新放进启动关键路径。
- 无代理场景不要为了接口统一而强行创建代理 transport。
- 非当前平台的客户端、配置、网络对象不要同步初始化。
- `httpx` 在 Windows 上的默认环境探测有真实成本，除非确实需要继承系统环境，否则优先显式关闭 `trust_env`。

## 回归关注点

如果后面再次出现“Web 端抖音明显慢于 GUI 端”，优先按下面顺序排查：

1. `Parameter.update_params()` 是否又回到了远程优先
2. `create_client()` / `request_params()` 是否重新引入了无条件 `mounts`
3. 是否重新把 `trust_env=True` 带回默认路径
4. 是否重新在抖音任务里初始化了 `client_tiktok`

## 相关文件

- `app/core/lib/douyin/tools/parameter.py`
- `app/core/lib/douyin/tools/session.py`
- `tests/test_douyin_parameter.py`
- `tests/test_downloaders.py`
