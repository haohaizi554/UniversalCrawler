# WebUI 增量路由和静态缓存修复

## 背景

在生产级体验验收时，WebUI 设置页通过浏览器真实加载验证。页面视觉布局正常，但控制台出现 `Failed to load resource: the server responded with a status of 404`。

## 现象

Playwright 采样发现失败资源不是图片或 favicon，而是：

```text
/api/frontend/delta?since_version=0
```

这会让浏览器控制台出现错误，并迫使前端退回全量状态刷新。页面可用，但增量状态通道和生产体验不一致。

## 根因

项目里存在两条 REST 组装路径：

- `app.web.rest_router.build_rest_router()` 已经提供 `/api/frontend/delta`
- `app.web.server.create_app()` 直接注册基础路由，但缺少同名 delta 端点

测试验证服务使用 `tests.web_test_app:app`，它走的是 `create_app()`，因此暴露了路由漂移。

同时，`index.html` 中 CSS/JS 使用裸路径 `/static/app.css` 和 `/static/app.js`。修复 CSS 后，已有浏览器会继续命中旧缓存，造成“代码已改但 computed style 未更新”的假象。

## 修复

1. 在 `app/web/server.py` 中补齐 `/api/frontend/delta`，与 `rest_router` 的返回结构保持一致。
2. 给 `app/web/static/index.html` 的 CSS/JS 加资源版本参数：

```html
<link rel="stylesheet" href="/static/app.css?v=20260628-config-hotload" />
<script src="/static/app.js?v=20260628-config-hotload" defer></script>
```

3. 补充回归测试：

- `tests/test_fastapi_endpoints.py::StateEndpointTests::test_frontend_delta_endpoint_matches_rest_router_contract`
- `tests/test_web_browser.py::StaticAssetsTests::test_static_assets_are_cache_busted`

## 经验

当项目同时存在“组合式路由”和“直接 create_app 路由”时，新增 API 必须同步两条路径，或者抽出共享注册函数。前端静态资源在生产环境应有明确版本，避免升级后旧 CSS/JS 缓存掩盖真实效果。
