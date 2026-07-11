# 大型前端测试与 CSS 职责拆分实施计划

> **执行要求：** 按任务顺序实施；每个任务先建立可观察基线或失败守卫，再迁移实现。不得以固定 `sleep` 掩盖异步问题。

**Goal:** 将两个大型前端测试文件与 `app.css` 按稳定职责拆分，同时保持测试节点、浏览器生命周期、CSS 级联结果、打包资产和产品行为不变。

**Architecture:** 浏览器测试采用“非收集 mixin + 唯一聚合 TestCase”；统一前端契约采用“共享基础设施 + 显式领域 TestCase”；CSS 采用 HTML 显式有序加载的责任样式表，并由真实加载顺序生成测试 bundle。

**Tech Stack:** Python 3.13、pytest/unittest、PyQt6、Playwright、原生 HTML/CSS、FastAPI 静态资源、PyInstaller 打包。

## 全局约束

- 不修改测试方法名和断言语义。
- 不增加浏览器或 Web 服务启动次数。
- 不新增第三方依赖、CSS 构建器或运行时动态加载器。
- 不使用 `time.sleep` 或 Playwright 固定等待。
- CSS 只按原文件连续区段迁移，禁止在拆分阶段重排选择器。
- 所有新 CSS 必须进入 HTML、静态资源测试和打包资产清单。
- 迁移前基线：两个目标测试文件共收集 `279` 个节点。
- 最终必须比较迁移前后的规范化测试方法集合，并运行全量测试。

---

## Task 1：锁定收集、资源与规模契约

**Files:**
- Create: `tests/test_large_frontend_file_boundaries.py`
- Modify: `tests/test_web_browser.py`
- Modify: `tests/test_unified_frontend_contract.py`

- [ ] 建立迁移前测试方法清单，记录两个原始类中的 `test_*` 方法名。
- [ ] 新增浏览器 case 模块不得被独立收集的守卫。
- [ ] 新增测试 support 模块不得定义 `test_*` 方法的守卫。
- [ ] 新增目标文件硬上限守卫：测试模块 1500 行、CSS 模块 1000 行。
- [ ] 新增 CSS 资产必须由 `index.html` 按固定顺序且仅一次引用的守卫。
- [ ] 运行守卫测试，确认在尚未拆分时只有预期的规模断言失败。

**验证：**

```powershell
python -m pytest tests/test_large_frontend_file_boundaries.py -q
python -m pytest tests/test_web_browser.py tests/test_unified_frontend_contract.py --collect-only -q
```

## Task 2：提取浏览器测试基础设施

**Files:**
- Create: `tests/web_browser_support.py`
- Modify: `tests/test_web_browser.py`

- [ ] 将 Playwright 检测、本地服务、HTTP 就绪等待等模块级辅助函数迁入 support。
- [ ] 将 `setUpClass`、`tearDownClass`、页面重置、服务重启、导航就绪和平台选项等待迁入共享基类。
- [ ] 保持静态资源、WebSocket、可访问性和设计规范测试仍在入口文件。
- [ ] 保持 `WebUIBrowserTests` 类名和测试节点前缀不变。
- [ ] 运行静态测试及少量浏览器 smoke，确认服务只启动一次。

**验证：**

```powershell
python -m pytest tests/test_web_browser.py::StaticAssetsTests -q
python -m pytest tests/test_web_browser.py::WebUIBrowserTests::test_01_index_loads -q
```

## Task 3：按职责拆分浏览器测试 case

**Files:**
- Create: `tests/web_browser_cases/__init__.py`
- Create: `tests/web_browser_cases/smoke_and_assets.py`
- Create: `tests/web_browser_cases/localization_and_logs.py`
- Create: `tests/web_browser_cases/dialogs_and_keyboard.py`
- Create: `tests/web_browser_cases/playback.py`
- Create: `tests/web_browser_cases/settings.py`
- Create: `tests/web_browser_cases/runtime_and_lists.py`
- Modify: `tests/test_web_browser.py`

- [ ] 逐个完整方法迁移，保持方法文本和名称不变。
- [ ] case 类不继承 `unittest.TestCase`，类名不以 `Test` 开头。
- [ ] 入口中的唯一 `WebUIBrowserTests` 按领域继承 mixin 和共享基类。
- [ ] 处理领域私有 helper：仅单领域使用的随测试迁移，共享 helper 留在 support。
- [ ] 比较迁移前后浏览器测试方法集合。
- [ ] 运行全部浏览器测试；若 Playwright 不可用，只允许项目既有 skip 语义。

**验证：**

```powershell
python -m pytest tests/test_web_browser.py --collect-only -q
python -m pytest tests/test_web_browser.py -q
```

## Task 4：提取统一契约共享基类

**Files:**
- Create: `tests/unified_frontend_contract_support.py`
- Modify: `tests/test_unified_frontend_contract.py`

- [ ] 迁移 `QApplication` 单例、shell 生命周期、日志/表格等待和 combo popup helper。
- [ ] support 不持有领域断言或测试方法。
- [ ] 保持每个测试独立清理 widget/shell。
- [ ] 运行代表性 GUI 测试，确认 QApplication 与资源清理语义不变。

**验证：**

```powershell
python -m pytest tests/test_unified_frontend_contract.py -k "shell or combo or log" -q
```

## Task 5：按领域拆分统一前端契约

**Files:**
- Create: `tests/test_unified_frontend_shell_contract.py`
- Create: `tests/test_unified_frontend_settings_contract.py`
- Create: `tests/test_unified_frontend_i18n_logs_contract.py`
- Create: `tests/test_unified_frontend_task_pages_contract.py`
- Create: `tests/test_unified_frontend_static_contract.py`
- Modify: `tests/test_unified_frontend_contract.py`

- [ ] 壳层、布局、导航、通用表格和活动队列测试迁入 shell 模块。
- [ ] 设置页、平台控件、弹窗与顶部栏设置契约迁入 settings 模块。
- [ ] 语言、日志、动态翻译与日志详情迁入 i18n/logs 模块。
- [ ] 四态列表、已完成、失败详情与分页迁入 task pages 模块。
- [ ] Web 静态责任边界与跨端一致性断言迁入 static 模块。
- [ ] 原入口只保留架构边界守卫和迁移说明，不重新导出测试类。
- [ ] 比较迁移前后统一契约测试方法集合。

**验证：**

```powershell
python -m pytest tests/test_unified_frontend_*contract.py --collect-only -q
python -m pytest tests/test_unified_frontend_*contract.py -q
```

## Task 6：按原级联顺序拆分 CSS

**Files:**
- Create: `app/web/static/task_pages.css`
- Create: `app/web/static/media_logs.css`
- Create: `app/web/static/settings.css`
- Create: `app/web/static/overlays_responsive.css`
- Modify: `app/web/static/app.css`
- Modify: `app/web/static/index.html`

- [ ] 在原 CSS 中识别连续、语法闭合的职责区段。
- [ ] 迁移前记录 CSS 规则顺序指纹。
- [ ] 以连续区段迁移，不在本任务中格式化或去重。
- [ ] `index.html` 使用五个显式 `<link>`，统一 cache-busting 版本。
- [ ] 验证按 link 顺序拼接后的内容与迁移前 CSS 规范化内容一致。
- [ ] 验证每个 CSS 文件大括号平衡且无空文件。

**验证：**

```powershell
python -m pytest tests/test_large_frontend_file_boundaries.py -q
python -m pytest tests/test_web_browser.py::StaticAssetsTests -q
```

## Task 7：更新测试 bundle 与打包资产

**Files:**
- Modify: `tests/test_web_browser.py`
- Modify: `tests/test_unified_frontend_static_contract.py`
- Modify: `tests/test_packaging.py`
- Modify: `packaging/build_installer.py`（仅在资产显式枚举时）
- Modify: relevant PyInstaller spec/config（仅在资产显式枚举时）

- [ ] 新增共享 CSS 清单读取 helper，顺序以 `index.html` 为准。
- [ ] 跨文件 CSS 断言使用拼接 bundle。
- [ ] 单文件责任断言直接读取对应文件。
- [ ] 静态资产测试覆盖五个 CSS 文件及缓存版本一致性。
- [ ] 安装器和便携包测试验证所有 CSS 均随包发布。

**验证：**

```powershell
python -m pytest tests/test_packaging.py tests/test_web_browser.py::StaticAssetsTests tests/test_unified_frontend_static_contract.py -q
```

## Task 8：完成架构守卫与文档

**Files:**
- Modify: `tests/test_large_frontend_file_boundaries.py`
- Modify: `docs/engineering/frontend-refresh-and-concurrency.md`
- Modify: `app/web/INTERACTION_MAP.md`
- Modify: `packaging/README.md`（资产清单变化时）

- [ ] 锁定 case/support 的命名和依赖方向。
- [ ] 锁定 CSS 文件顺序、唯一引用和规模上限。
- [ ] 记录各测试/CSS 模块所有权与新增代码落点。
- [ ] 记录迁移后的测试数量、焦点耗时和全量耗时。
- [ ] 记录禁止用固定 sleep、必须按真实资源顺序构建静态 bundle 的经验。

## Task 9：最终验证

- [ ] 运行 `ruff check` 覆盖所有新增/修改 Python 文件。
- [ ] 运行两个测试家族并核对方法集合。
- [ ] 运行 packaging 测试。
- [ ] 运行完整测试套件。
- [ ] 运行 `git diff --check`。
- [ ] 检查工作区只包含本计划相关改动。

**最终命令：**

```powershell
python -m ruff check tests/test_web_browser.py tests/web_browser_support.py tests/web_browser_cases tests/unified_frontend_contract_support.py tests/test_unified_frontend_*contract.py tests/test_large_frontend_file_boundaries.py
python -m pytest tests/test_web_browser.py tests/test_unified_frontend_*contract.py tests/test_large_frontend_file_boundaries.py tests/test_packaging.py -q
python -m pytest -q
git diff --check
```

## 完成定义

- 浏览器测试与统一契约测试的原始 `test_*` 方法集合完全保留。
- 浏览器测试仍只有一个昂贵生命周期。
- `test_web_browser.py`、各领域测试模块不超过 1500 行。
- `app.css` 和各责任 CSS 不超过 1000 行。
- CSS 拼接顺序、浏览器视觉和打包资产无回归。
- 全量测试通过，工程文档同步最新基线。
