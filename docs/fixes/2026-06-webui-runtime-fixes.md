# WebUI 运行时修复总览（2026-06）

## 背景

WebUI 在增量路由、静态缓存和前端状态同步上出现过几类问题：前端增量更新后页面没有刷新、静态资源缓存导致旧 JS/CSS 残留、Web 服务和 WebUI 对配置快照的理解不一致。

这些问题的核心不是某个页面渲染失败，而是 WebUI 的状态来源、资源版本和后端增量接口之间缺少明确约束。

## 修复结论

- WebUI 页面更新必须以 `frontend_state` 和 `frontend_delta` 为核心，不应靠局部 DOM 自己猜状态。
- 静态资源更新后要考虑缓存失效策略，避免浏览器继续运行旧前端代码。
- REST 与 WebSocket 都应携带或理解前端版本，必要时返回可直接应用的 `frontend_delta`。
- 前端渲染应按 section 调度，避免单个设置或日志变化触发全页重绘。
- WebUI 的设置项、语言目录和主题状态必须与 GUI 共用后端契约。

## 归档记录

以下文档是当时排查过程的原始记录，已经被本文合并为当前结论：

- [archive/2026-06-28-webserver-frontend-delta-cache.md](archive/2026-06-28-webserver-frontend-delta-cache.md)
- [archive/2026-06-webui-incremental-route-cache.md](archive/2026-06-webui-incremental-route-cache.md)
