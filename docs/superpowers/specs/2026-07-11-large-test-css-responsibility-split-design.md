# 大型前端测试与 CSS 职责拆分设计

## 1. 背景

当前以下三个文件已经超过适合长期维护的规模：

- `tests/test_web_browser.py`：约 6500 行，混合静态资源、浏览器生命周期、语言、日志、弹窗、播放、设置和运行态压力测试。
- `tests/test_unified_frontend_contract.py`：约 4800 行，混合 GUI 壳层、设置、日志、四态列表、失败页以及 Web 静态契约。
- `app/web/static/app.css`：约 3600 行，混合设计令牌、壳层、任务页、媒体、日志、设置、弹窗和响应式规则。

问题不只是文件过长。三个文件都同时承担了多个变化原因，导致代码审查范围扩大、冲突概率增加、测试归属不清，并提高了无意改变浏览器生命周期或 CSS 级联顺序的风险。

本次拆分以长期工程治理为目标，不做机械按行切割。

## 2. 目标

1. 按稳定职责拆分三个大文件，使目录结构能直接表达功能所有权。
2. 保持测试数量、测试语义、浏览器启动次数和服务生命周期不变。
3. 保持 CSS 选择器的原始先后顺序和最终级联结果不变。
4. 建立依赖方向与文件规模守卫，防止职责重新聚合到单一文件。
5. 为后续 GUI/WebUI 同步、日志性能治理和长期测试扩展提供稳定落点。

## 3. 非目标

- 不修改产品行为、视觉规范、接口协议或测试断言语义。
- 不重构下载器、爬虫或后端业务算法。
- 不引入新的第三方依赖、测试框架或 CSS 构建工具。
- 不借本次拆分清理无关代码。
- 不使用固定 `sleep` 替代条件等待。

## 4. 设计原则

### 4.1 职责优先于行数

文件规模阈值用于发现边界失效，不用于决定切割位置。每个新模块必须只有一个主要变化原因，并拥有清晰的输入、输出和依赖方向。

### 4.2 昂贵资源只初始化一次

浏览器测试的 Chromium、浏览器上下文、页面和本地服务属于昂贵资源。拆分测试方法时必须保留单一聚合测试类和单一 `setUpClass`/`tearDownClass` 生命周期，不能让每个职责模块各自启动浏览器或服务。

### 4.3 显式模块优于隐式魔法

统一前端契约测试不需要共享昂贵浏览器资源，因此采用显式领域测试模块和共享基类，不使用动态导入、运行时生成测试类或复杂收集钩子。

### 4.4 CSS 加载顺序就是公共契约

拆分后的多个 CSS 文件按原文件中的连续区段加载。跨文件顺序必须与原选择器顺序一致，后置覆盖规则不得提前。禁止使用阻塞式 `@import`；由 `index.html` 显式声明资源及加载顺序。

## 5. 浏览器测试架构

### 5.1 目标结构

```text
tests/
  test_web_browser.py
  web_browser_support.py
  web_browser_cases/
    __init__.py
    smoke_and_assets.py
    localization_and_logs.py
    dialogs_and_keyboard.py
    playback.py
    settings.py
    runtime_and_lists.py
```

### 5.2 文件职责

- `web_browser_support.py`
  - Playwright 可用性检测。
  - 本地 Web 服务启动、就绪等待和关闭。
  - 浏览器测试共享基类及页面辅助方法。
  - 条件等待、重启服务、平台选项等待等通用能力。

- `web_browser_cases/*.py`
  - 只定义非 `TestCase` 的职责 mixin。
  - 每个 mixin 仅包含对应领域的测试方法和领域内私有辅助方法。
  - 文件名不以 `test_` 开头，避免 pytest/unittest 独立收集 mixin。

- `test_web_browser.py`
  - 保留静态资源、WebSocket 消息类型、可访问性和设计规范等轻量测试类。
  - 定义唯一可收集的 `WebUIBrowserTests` 聚合类。
  - 聚合类继承所有职责 mixin 和共享浏览器基类。
  - 不复制测试方法，不创建第二套浏览器生命周期。

### 5.3 依赖方向

```text
test_web_browser.py
  -> web_browser_cases/*
  -> web_browser_support.py

web_browser_cases/*
  -> web_browser_support.py 提供的实例契约
  -X-> test_web_browser.py
```

职责 mixin 不得反向导入聚合入口，不得在模块导入期间启动浏览器、线程或服务。

### 5.4 收集与生命周期约束

- `WebUIBrowserTests` 仍只收集一次。
- 浏览器服务、Playwright、Chromium context 和 page 仍只初始化一次。
- 测试方法名保持不变，以便历史失败定位和 CI 趋势继续可比。
- 迁移前后比较 `pytest --collect-only` 的节点集合，不只比较总数。

## 6. 统一前端契约测试架构

### 6.1 目标结构

```text
tests/
  unified_frontend_contract_support.py
  test_unified_frontend_contract.py
  test_unified_frontend_shell_contract.py
  test_unified_frontend_settings_contract.py
  test_unified_frontend_i18n_logs_contract.py
  test_unified_frontend_task_pages_contract.py
  test_unified_frontend_static_contract.py
```

### 6.2 文件职责

- `unified_frontend_contract_support.py`
  - `QApplication` 单例初始化。
  - GUI 壳层创建、关闭和清理。
  - 表格、日志、组合框和异步状态等待辅助方法。
  - 只提供测试基础设施，不定义可收集测试。

- `test_unified_frontend_shell_contract.py`
  - App shell、布局、导航、表格和活动队列契约。

- `test_unified_frontend_settings_contract.py`
  - 基础、下载、平台、播放、日志、外观设置及弹窗契约。

- `test_unified_frontend_i18n_logs_contract.py`
  - GUI/WebUI 语言热切换、日志本地化、动态文案和日志详情契约。

- `test_unified_frontend_task_pages_contract.py`
  - 下载队列、正在下载、已完成、失败列表及详情面板契约。

- `test_unified_frontend_static_contract.py`
  - Web 静态模块边界、资源引用、GUI/WebUI 字段和行为一致性契约。

- `test_unified_frontend_contract.py`
  - 保留小型架构守卫和历史入口说明。
  - 不导入并重新暴露其他模块的测试类，防止重复收集。

### 6.3 共享状态约束

- 各领域测试类显式继承共享基类。
- `QApplication` 继续复用单例；每个用例自行清理创建的 shell/widget。
- 异步 UI 使用条件等待或现有 idle/ack 契约，不增加固定延迟。
- 共享基类不得积累领域断言，领域私有辅助方法优先留在对应模块。

## 7. CSS 架构

### 7.1 目标结构

```text
app/web/static/
  app.css
  task_pages.css
  media_logs.css
  settings.css
  overlays_responsive.css
```

### 7.2 文件职责

- `app.css`
  - CSS 变量、浅色/深色设计令牌。
  - reset、排版、通用表单控件。
  - 应用壳层、顶部栏、侧栏、状态栏和共享布局原语。
  - 继续作为打包和安装器要求的核心入口资产存在。

- `task_pages.css`
  - 四态任务页、表格、分页、详情栏、队列和失败页。

- `media_logs.css`
  - 播放器、媒体预览、速度图表、日志中心和日志详情。

- `settings.css`
  - 设置壳层、设置分组、平台表格、代理组合控件和外观控件。

- `overlays_responsive.css`
  - 弹窗、下拉浮层、通知、焦点覆盖规则和响应式断点。

### 7.3 加载方式

`index.html` 按以下固定顺序显式加载：

```html
<link rel="stylesheet" href="/static/app.css?...">
<link rel="stylesheet" href="/static/task_pages.css?...">
<link rel="stylesheet" href="/static/media_logs.css?...">
<link rel="stylesheet" href="/static/settings.css?...">
<link rel="stylesheet" href="/static/overlays_responsive.css?...">
```

迁移以原 `app.css` 的连续区段为单位。若一个领域规则依赖后置覆盖，则覆盖规则仍保留在更后加载的文件，不为追求名称纯度而改变级联位置。

### 7.4 测试读取方式

静态契约测试新增统一 `_css_bundle()`：

1. 从 `index.html` 解析实际样式表顺序。
2. 读取并按该顺序拼接本地 CSS 内容。
3. 所有跨文件选择器/令牌断言使用该 bundle。
4. 单文件所有权断言直接读取责任文件。

测试不得继续假定所有样式都位于 `app.css`。

## 8. 工程守卫

### 8.1 文件规模

新增静态守卫，采用软硬两级阈值：

- 测试职责模块目标不超过 1200 行，硬上限 1500 行。
- CSS 职责模块目标不超过 800 行，硬上限 1000 行。
- 聚合入口仅负责装配，不允许重新承载大段领域实现。

超过目标值应在 CR 中说明；超过硬上限直接使守卫测试失败。

### 8.2 边界守卫

- 浏览器 case 模块不得定义 `unittest.TestCase` 子类。
- 浏览器 case 文件不得以 `test_` 命名。
- 统一契约 support 模块不得包含 `test_*` 方法。
- CSS 文件必须全部由 `index.html` 引用且仅引用一次。
- CSS 引用顺序由测试锁定。
- 打包资产清单必须包含所有新增 CSS 文件。

### 8.3 行为守卫

- 测试节点集合迁移前后保持一致；新增架构守卫除外。
- 浏览器进程/服务启动次数保持一致。
- 不允许新增固定 `sleep`。
- CSS 视觉回归以现有 Playwright 截图、关键布局断言和主题测试验证。

## 9. 迁移步骤

1. 记录迁移前 pytest 节点清单、总数和目标测试耗时。
2. 提取浏览器 support，再逐领域迁移 mixin，保持测试方法名不变。
3. 创建统一契约共享基类，按领域迁移显式测试类。
4. 按原顺序拆分 CSS，更新 `index.html`、测试和打包资产清单。
5. 加入收集、文件规模、依赖方向和 CSS 加载顺序守卫。
6. 运行焦点测试、静态检查和全量测试。
7. 将新目录职责和最新全量基线同步到工程文档。

每一步都必须可独立验证；发现收集数量、生命周期或视觉级联漂移时立即停止后续迁移。

## 10. 验收标准

- 三个原始大文件均降到职责明确的薄入口或核心样式规模。
- 浏览器测试只启动一套服务和浏览器生命周期。
- 原有测试节点全部保留且无重复收集。
- CSS 在浅色/深色、各强调色和不同窗口尺寸下无视觉回归。
- 安装器与便携包包含全部 CSS 资产。
- 焦点测试、`ruff check` 和 `python -m pytest -q` 全部通过。
- 工程文档记录新模块所有权、扩展规则和最新测试数量/耗时。

## 11. 风险与缓解

### 测试被重复收集

缓解：case 模块不以 `test_` 命名且不继承 `TestCase`；统一契约模块不经聚合入口重新导出测试类；迁移前后对比完整节点集合。

### 浏览器生命周期被放大

缓解：只保留一个可收集聚合类和一个共享基类生命周期，并对服务/浏览器启动次数增加测试或日志断言。

### CSS 级联顺序变化

缓解：按原文件连续区段迁移，显式锁定 link 顺序，测试 bundle 使用真实加载顺序，避免 `@import`。

### 打包遗漏静态资产

缓解：更新打包资产清单，并在 packaging 测试中逐项验证新增 CSS 文件存在。

### 拆分后再次聚合

缓解：文件规模、导入方向和模块命名守卫进入常规测试；文档明确新测试和新样式应落入哪个责任模块。

## 12. 长期扩展规则

- 新浏览器测试先选择现有领域 mixin；只有出现新的独立变化原因时才新增 case 模块。
- 新 GUI/WebUI 契约进入明确领域模块，不进入共享 support。
- 新 CSS 规则归属于拥有该组件的样式文件；跨领域原语才进入 `app.css`。
- 新模块必须同时更新责任清单、打包清单和架构守卫。
- 每次全量测试基线发生显著变化时，同步工程文档中的测试数量和耗时。
