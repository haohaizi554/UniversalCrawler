# WebUI `app.js` 职责拆分设计

## 状态

- 日期：2026-07-10
- 范围：`app/web/static/app.js` 及其静态资源加载、契约测试
- 目标：按职责拆分约 239 KB 的单体脚本，保持 GUI/WebUI 可见行为、后端接口和打包方式不变
- 约束：不引入 Node.js、打包器或新的运行时依赖

## 背景

`app/web/static/app.js` 当前同时承担应用启动、前端状态同步、四态列表、日志本地化、日志查询、设置控制、弹窗、播放预览和通用工具等职责。文件内部已经调用多个 `window.Ucp*` 服务，但控制层仍集中在一个脚本中，导致以下问题：

1. 修改任一页面都需要理解大量无关状态和函数。
2. 日志本地化与查询代码占据大段连续区域，难以独立测试和演进。
3. 页面控制器共享可变全局变量，职责边界不清晰。
4. HTML 内联事件依赖全局函数，使直接迁移到 ES Module 的风险较高。
5. 静态资源加载、PyInstaller 打包和浏览器契约测试都把 `app.js` 视为唯一主入口。

## 目标与非目标

### 目标

- 每个模块只负责一个业务域，并通过明确接口访问共享能力。
- `app.js` 收敛为启动、导航、共享上下文和兼容编排入口。
- 保留现有无构建静态资源部署方式和浏览器缓存版本参数。
- 保留 `/api/frontend/state`、`/api/frontend/delta`、WebSocket 和 worker 协议。
- 保留现有 HTML 内联事件入口，逐步转为薄兼容包装。
- 新模块拥有契约测试，加载顺序错误能在测试中被发现。
- 拆分后不增加全量渲染、同步日志解析或 UI 线程阻塞。

### 非目标

- 本轮不重写页面 HTML 或 CSS。
- 本轮不迁移到 React、Vue、TypeScript、Vite 或其他构建体系。
- 本轮不修改 GUI 逻辑、后端数据结构或下载业务算法。
- 本轮不删除已有兼容全局函数，除非已有测试证明没有消费者。

## 方案比较

### 方案 A：仅抽取最大的日志和播放代码

改动较小，但四态列表、设置、弹窗和状态同步仍然耦合在主文件中，只能短期降低行数，无法形成稳定架构边界。

### 方案 B：按职责拆分为经典脚本服务对象

每个文件使用 IIFE 封装私有状态，通过 `window.Ucp*` 暴露窄接口，并由 `configure()` 注入共享依赖。这与现有 `settings_render.js`、`task_render.js` 和 `playback_state.js` 一致，不需要构建工具，能够被当前打包和浏览器环境直接加载。

### 方案 C：迁移到原生 ES Module

依赖关系最显式，但会同时改变脚本加载、全局事件、worker 资源路径、测试装载和 PyInstaller 静态资源契约。收益存在，但超出本轮安全拆分范围。

采用方案 B。它能形成清晰职责边界，同时控制运行时和发布风险。

## 总体架构

浏览器先加载无状态基础服务和各业务控制器，最后加载 `app.js`。`app.js` 创建唯一共享上下文，向控制器注入状态访问器和跨域操作。控制器不持有 `frontendState` 的副本，不直接修改其他控制器的私有状态。

```text
index.html
  -> 基础服务：i18n/custom-select/render helpers
  -> 业务服务：log i18n/list pages/log center/settings/dialog/playback
  -> app.js
       -> 创建 AppContext
       -> configure(依赖)
       -> 安装兼容入口
       -> 启动首屏状态同步
```

共享状态只有一个所有者：`app.js`。业务模块通过 `getState()` 读取，通过明确的回调请求变更。任何模块都不得缓存整个状态快照。

## 模块边界

### `frontend_runtime.js`

负责：

- `/api/frontend/state` 首屏快照加载。
- `/api/frontend/delta` 增量拉取和版本连续性检查。
- WebSocket 连接、重连、旧事件兼容。
- 同帧渲染合并和脏 section 调度。
- 页面退出时关闭 socket、worker 和定时器。

不负责具体页面 DOM。模块只把变更 section 通知 `app.js` 的渲染路由。

### `list_pages.js`

负责：

- 下载队列、正在下载、已完成、失败列表的分页状态。
- `list_page_worker.js` 生命周期、请求序列和过期响应丢弃。
- 四态列表行渲染、选中项协调、详情投影。
- 页码、每页条数和键盘列表导航。

不负责播放实现、日志解析或后端状态同步。

### `log_i18n.js`

负责：

- 结构化日志字段别名。
- 动态日志短语、本地化片段和平台名称映射。
- 日志类型、范围、阶段和事件码的显示文本。
- 向日志 worker 提供可序列化的翻译提示。

该模块必须是纯转换服务；不得读取 DOM、文件或网络。

### `log_center.js`

负责：

- 日志标签、筛选器、分页和选中项。
- `log_query_worker.js` 与 `log_detail_worker.js` 生命周期。
- 查询签名、请求序列、过期结果丢弃和 fallback。
- 日志表格、空状态、详情、复制、导出和 Trace ID 操作。

日志文本转换统一委托给 `log_i18n.js`，不得在 UI 渲染函数中重新维护正则映射。

### `settings_controller.js`

负责：

- 设置分组、可见性和认证状态刷新。
- 基础、下载、平台、播放、日志和外观设置的更新编排。
- 自定义代理选择与输入提交。
- 设置热更新后的局部状态同步。

具体设置 HTML 继续由 `settings_render.js` 生成。

### `dialog_controller.js`

负责：

- 目录选择弹窗。
- Windows 默认打开方式绑定弹窗。
- 下载任务选择弹窗。
- 弹窗焦点、Enter/Escape 快捷键和关闭清理。

弹窗关闭后不得残留全局键盘处理状态。

### `playback_controller.js`

负责：

- 已完成资源预览、图片/视频分流。
- 播放、暂停、进度、上一项、下一项和全屏。
- 播放位置恢复、自动播放和图片自动切换。
- 媒体校验、元数据回填和播放失败展示。

纯播放状态与格式化继续复用 `playback_state.js` 和 `media_display.js`。

### `app.js`

只保留：

- 单一 `frontendState` 和跨页面选中状态所有权。
- `AppContext` 创建和业务模块 `configure()`。
- 应用启动、页面导航、顶栏、状态栏和工具箱编排。
- 通用的 `byId`、`esc`、`escAttr`、`cssEscape` 等小型基础函数。
- HTML 内联事件和旧浏览器测试需要的薄兼容包装。

兼容包装只允许转发调用，不得重新实现业务逻辑。

## 内部接口契约

每个业务模块暴露单个命名空间，例如：

```javascript
window.UcpLogCenter = Object.freeze({
  configure,
  render,
  select,
  setPage,
  setPageSize,
  dispose,
});
```

`configure()` 接收按需依赖，典型字段包括：

- `getState()`：读取最新共享状态。
- `getLanguage()` / `t()`：语言与静态文本翻译。
- `sendWS(type, data)`：发送后端动作。
- `frontendAction(action, payload)`：调用统一动作入口。
- `scheduleRender(section)`：请求局部渲染。
- `byId()` / `esc()` / `escAttr()`：受控 DOM 与转义工具。
- `onSelectionChange(domain, id)`：请求更新共享选中状态。

模块未配置时应安全降级或抛出可识别的初始化错误，不得静默执行部分逻辑。

## 加载顺序

`index.html` 中的脚本顺序固定为：

1. `i18n.js`
2. `custom_select.js`
3. `media_display.js`
4. `log_display.js`
5. `platform_limits.js`
6. `settings_render.js`
7. `task_render.js`
8. `playback_state.js`
9. `log_i18n.js`
10. `frontend_runtime.js`
11. `list_pages.js`
12. `log_center.js`
13. `settings_controller.js`
14. `dialog_controller.js`
15. `playback_controller.js`
16. `app.js`

所有脚本继续使用 `defer`。每个新增静态资源都带统一版本参数，并加入静态资源、打包和浏览器装载测试。

## 错误处理与生命周期

- worker、WebSocket 和定时器均由所属模块创建和释放。
- 每个异步请求携带递增序列；旧响应不得覆盖新状态。
- worker 不可用时保留现有同步 fallback，但 fallback 必须被调度，避免阻塞同一交互帧。
- 模块初始化失败时记录明确错误并保留其他页面基本可用性。
- 页面退出统一调用各模块 `dispose()`，清理必须幂等。
- 用户可见错误继续走现有状态/日志通道，不新增浏览器原生警告弹窗。

## 兼容与迁移策略

采用纵向切片迁移，每次只迁移一个职责域：

1. 先为模块加载顺序、导出接口和 `app.js` 大小建立失败测试。
2. 抽取纯函数最多的 `log_i18n.js`。
3. 抽取 `log_center.js`，保持现有 worker 协议。
4. 抽取 `list_pages.js`。
5. 抽取 `settings_controller.js` 与 `dialog_controller.js`。
6. 抽取 `playback_controller.js`。
7. 最后抽取 `frontend_runtime.js`，收敛 `app.js`。

每一步都保留兼容包装并运行相关测试。只有完整调用链证明没有消费者后，才允许在后续任务中删除包装。

## 测试策略

### 静态契约测试

- 新增模块文件全部存在并被 `index.html` 按指定顺序加载。
- `app.js` 不再包含已迁移模块的核心实现标记。
- 每个 `window.Ucp*` 服务暴露预期接口。
- 打包清单包含所有新增文件。
- 静态资源响应继续使用禁缓存策略。

### 单元测试

- 日志本地化纯函数覆盖中英文、结构化字段和动态片段。
- 分页 worker 请求序列和过期响应丢弃。
- 各控制器 `dispose()` 幂等并释放资源。
- 未配置依赖的失败行为明确。

### 浏览器集成测试

- 首屏加载无脚本异常。
- 四态页面切换、分页、选中和详情更新正常。
- 日志筛选、详情、语言切换和 worker fallback 正常。
- 设置热更新、代理自定义输入和三个弹窗正常。
- 播放、进度、全屏、图片预览和元数据回填正常。
- 快速导航不会产生旧响应回写、原生空白窗或重复事件处理器。

### 回归测试

- 先运行静态与 WebUI 焦点测试。
- 再运行完整 `python -m pytest -q`。
- 记录测试数量、跳过数量、警告和耗时。

## 验收标准

- `app.js` 只承担应用编排和兼容入口，不再含日志映射、四态分页、设置控制、弹窗或播放核心实现。
- 任一业务模块可以独立理解其职责、依赖和生命周期。
- 新增模块加载顺序、导出接口和打包覆盖均有自动化测试。
- GUI/WebUI 可见行为和后端协议不变。
- 页面快速切换、语言切换、日志洪峰和播放交互无新增闪烁、卡顿或异常退出。
- 全量测试通过，且没有新增警告。

