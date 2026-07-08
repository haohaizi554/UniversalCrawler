# WebUI 运行时修复总览（2026-06）

## 背景

WebUI 在增量路由、静态缓存和前端状态同步上出现过几类问题：前端增量更新后页面没有刷新、静态资源缓存导致旧 JS/CSS 残留、Web 服务和 WebUI 对配置快照的理解不一致、真实 `create_app()` 路径和组合式 REST router 路径存在接口漂移。

这些问题的核心不是某个页面渲染失败，而是 WebUI 的状态来源、资源版本和后端增量接口之间缺少明确约束。本文已吸收原 `archive/` 下 Web 服务 delta/cache 与 WebUI 增量路由缓存两份单点记录。

## 已合并的修复主题

- WebUI 页面更新必须以 `frontend_state` 和 `frontend_delta` 为核心，不应靠局部 DOM 自己猜状态。
- 静态资源更新后要考虑缓存失效策略，避免浏览器继续运行旧前端代码。
- REST 与 WebSocket 都应携带或理解前端版本，必要时返回可直接应用的 `frontend_delta`。
- 前端渲染应按 section 调度，避免单个设置或日志变化触发全页重绘。
- WebUI 的设置项、语言目录和主题状态必须与 GUI 共用后端契约。
- `app.web.server.create_app()` 和 `app.web.rest_router.build_rest_router()` 不能维护两套互相漂移的 API。

## 单点事故吸收

### Web 入口路由缓存与 delta 接口

曾经在执行 `pytest` 时多次出现 `SyntaxError: invalid non-printable character`，定位到 `app/web/server.py` 的 `/api/search` 附近；此前 `/api/frontend/delta` 也不存在，首页和静态资源没有禁缓存头。

处理时先回到可解析基线，再只加回当前需求功能：

- 增加 `/api/frontend/delta`，优先使用控制器 `get_frontend_delta`。
- `POST /api/frontend/action` 支持 `frontend_version`，返回时附带 `frontend_delta`。
- 为 `/` 与 `/static/*` 响应统一加入 `Cache-Control`、`Pragma`、`Expires` 禁缓存头。
- 保持既有错误码风格，避免修增量接口时破坏老契约。

吸收后的工程约束：

- 修复 Web 入口文件时，先保证文件可解析，再小步加回功能；不要在已损坏文件上继续叠补丁。
- REST API 与 WebSocket 状态更新链路需要保持一致。
- 首屏资源与 JS/CSS 必须有明确缓存策略，避免升级后旧资源残留。

### WebUI 增量路由和静态缓存

生产级体验验收中，WebUI 设置页视觉正常，但控制台出现：

```text
/api/frontend/delta?since_version=0
```

返回 404。根因是项目存在两条 REST 组装路径：

- `app.web.rest_router.build_rest_router()` 已经提供 `/api/frontend/delta`。
- `app.web.server.create_app()` 直接注册基础路由，但缺少同名 delta 端点。

测试验证服务走的是 `create_app()`，因此暴露路由漂移。同时，`index.html` 中 CSS/JS 使用裸路径，修复 CSS 后浏览器仍可能命中旧缓存，造成“代码已改但 computed style 未更新”的假象。

吸收后的工程约束：

- 新增 Web API 必须同步真实 `create_app()` 路径和组合式 router 路径，或者抽出共享注册函数。
- 前端静态资源在生产环境应有明确版本或禁缓存头。
- 浏览器端发现 delta 接口不可用时可以降级全量状态，但测试必须把这类 404 当作契约回归。
- 修改 WebUI CSS/JS 后，必须验证真实启动路径返回的新资源，不只看源码文件已变。

## 当前稳定约束

- `/api/frontend/state`、`/api/frontend/delta` 和 WebSocket `frontend_delta` 使用同一套状态构建语义。
- `frontend_version` 是前端动作和增量响应的契约字段，不能只在某一路由中生效。
- 首页、CSS、JS 等静态资源必须通过真实服务路径验证缓存头或版本参数。
- WebUI 设置页、主题、语言和平台数量单位必须消费 `FrontendStateService.settings_snapshot()`，不得在前端另写一套默认值。

## 验证基线

相关历史修复覆盖过：

- `python -m py_compile app/web/server.py`
- `tests/test_fastapi_endpoints.py::StateEndpointTests::test_frontend_delta_endpoint_matches_rest_router_contract`
- `tests/test_web_browser.py::StaticAssetsTests::test_static_assets_are_cache_busted`
- 全量 `pytest -q`

后续修改 Web 服务入口、REST router、WebSocket 前端状态、静态资源路径或缓存策略时，必须同时验证真实 `create_app()` 路径和组合式 router 路径。
