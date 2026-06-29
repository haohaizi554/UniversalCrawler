# 运行时故障记录：Web 入口路由缓存与 delta 接口修复（2026-06-28）

## 现象
- 执行 `pytest` 时多次出现 `SyntaxError: invalid non-printable character`，报错定位到 `app/web/server.py` 的 `@app.post("/api/search")` 附近。
- 在此之前，`/api/frontend/delta` 不存在，首页和静态资源未返回禁缓存头。

## 影响
- FastAPI 启动失败，导致大量后端接口与端到端/WebUI测试无法执行。
- Web 前后端首屏状态联动测试（`/api/frontend/delta`）与静态资源更新策略（cache-control）失败。

## 处理过程
1. 先用 `git checkout -- app/web/server.py` 回退到可解析基线版本。
2. 仅在基线上加回当前需求功能：
   - 增加 `GET /api/frontend/delta`，优先使用控制器 `get_frontend_delta`。
   - `POST /api/frontend/action` 支持 `frontend_version`，返回时附带 `frontend_delta`。
   - 为 `/` 与 `/static/*` 响应统一加入 `Cache-Control/Pragma/Expires` 禁缓存头。
3. 保持原有错误码风格（200 + `status/error`）不变，避免破坏既有契约。

## 验证
- `python -m py_compile app/web/server.py`
- `pytest -q`（1426 passed, 1 skipped）

## 收益
- REST API 与 WebSocket 状态更新链路保持一致。
- 首屏资源与 JS/CSS 不会被浏览器错误缓存，避免升级后出现旧资源残留。
