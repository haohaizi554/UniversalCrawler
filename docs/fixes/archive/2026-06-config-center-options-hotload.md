# 配置中心选项化与热加载修复

## 背景

配置中心需要同时服务 GUI 和 WebUI。问题集中在三个方向：前端控件允许任意键入、部分设置没有真实热加载反馈、GUI 与 WebUI 的状态来源不一致。

## 具有教学意义的问题

1. 自绘开关不可点击
   - 现象：`UiSwitch` 使用 `QCheckBox` 自绘，但 QSS 隐藏了原生 indicator，点击命中区域可能退化。
   - 修复：重写 `hitButton()`，让整颗 48x28 开关都参与命中判断。
   - 经验：自绘复用原生控件时，不能只改 paintEvent，还要检查原生控件的命中、焦点和可访问行为。

2. 字号/缩放热加载无感
   - 现象：`QApplication.setFont()` 已执行，但全局 QSS 写死 `font-size: 13px`，覆盖了字体设置。
   - 修复：让 `generate_stylesheet()` 接收字号和缩放参数，动态生成基础字号；设置页自己的局部 QSS 也必须按当前缩放重新生成，不能继续写死字号。
   - 经验：Qt 里 QSS 优先级高于应用字体，做主题或字号热加载时必须同时更新 stylesheet。

3. Cookie 认证状态写死
   - 现象：平台认证状态只按平台 ID 写死为已认证/未认证。
   - 修复：`FrontendStateService` 读取 `auth` 配置中的 Cookie 文件，并按平台关键 Cookie 判断状态。
   - 经验：状态展示必须来自真实数据源；否则 UI 会制造“看起来可用”的错误信号。

4. MissAV 代理配置参数错位
   - 现象：旧入口把 `proxy_url` 作为第二个参数传给 `update_missav_proxy()`，而该参数原本是 `port`。
   - 修复：新的 `update_missav_proxy(proxy_app, port | url, url)` 兼容旧调用，并统一写入 `proxy_app`、`proxy_type`、`proxy_port`、`proxy_url`。

5. 安装源只校验部分 WebUI 资源
   - 现象：安装包构建前只检查 `app.js` 和少量图标，若 `index.html`、`app.css` 或主/Web 图标漏包，安装器仍可能继续生成。
   - 修复：`packaging/build_installer.py` 的安装源完整性清单补齐 HTML、CSS、JS、GUI/Web 图标与设置图标，并同步测试和打包文档。
   - 经验：公共配置函数一旦有多个调用入口，应优先设计成容错的领域接口，而不是暴露易错的位置参数。

6. 下拉框打开态颜色回落
   - 现象：选择框获得焦点时有高亮，但展开选项后本体颜色回落，弹层还可能显示系统默认白色。
   - 修复：GUI 增加 `QComboBox:on`、弹层 `QAbstractItemView` 和自定义代理状态样式；WebUI 增加 select focus/active、option 背景和 `color-scheme`。
   - 经验：下拉框是“本体 + 弹层”两套绘制路径，主题适配必须同时覆盖。

7. 自定义代理提交时机不清晰
   - 现象：代理下拉框一旦设为可编辑，用户可以在任意预设上键入，容易把预设和自定义端点混成一个状态。
   - 修复：只有“自定义”或已有自定义端点进入可编辑状态；选择 Clash、v2rayN、sing-box 等预设时立即由后端转换，输入框保持只读。
   - 经验：可编辑下拉框要把“选择预设”和“输入自定义值”拆成明确状态，否则用户体验和配置语义都会漂移。

8. 真实 Web 启动路径仍然缓存旧前端
   - 现象：静态 `index.html` 已经给 CSS/JS 加了版本参数，但用户实际打开 WebUI 仍可能看到旧页面。
   - 根因：`app.web.static_router` 已实现禁缓存响应，但 `app.web.server.create_app()` 真实运行路径仍直接返回 `FileResponse(index.html)` 并挂载原生 `StaticFiles`。
   - 修复：`create_app()` 统一复用 `build_static_router()` 和 `mount_static_files()`，首页、`app.css`、`app.js` 都返回 `Cache-Control: no-store`。
   - 经验：修复静态资源缓存时必须检查所有启动入口；只改辅助路由模块，不等于用户打开的路径已经生效。

9. GUI 设置分类切换时旧控件短暂残留
   - 现象：切到“平台设置”后，旧“基础设置”控件可能在立即重绘/截图时仍被判定可见，标题区域也会有叠层感。
   - 根因：`QLayout.takeAt()` 后仅调用 `deleteLater()`，控件要等 Qt 处理 DeferredDelete 才真正离开父对象。
   - 修复：清理详情面板时只 `hide()` 并 `deleteLater()`，不要 `setParent(None)`；否则旧控件会在 deferred delete 前短暂成为隐藏 top-level，拖慢主题切换并提高空白小窗风险。
   - 经验：Qt 动态页面切换不能只依赖延迟销毁；需要让旧控件退出可见层级，同时保留父级归属直到删除事件处理完成。

10. 平台设置列宽只在静态测试里“通过”
    - 现象：GUI/WebUI 的平台默认数量标签在真实截图里被截断，Web 自定义代理输入框还会从右侧溢出；后续已统一区分“20 个视频（推荐）”和“1 页（推荐）”。
    - 修复：GUI 平台数量列加宽到 184px、代理列加宽到 328px；WebUI 改为四列表格，自定义端点在代理列下一行展开，并增加窄屏无横向滚动验证。
    - 经验：配置中心这种生产工具页必须用截图和 DOM 尺寸验证，不能只靠字符串/单元测试判断“控件存在”。
11. Windows 配置保存偶发 `PermissionError`
    - 现象：GUI/Web 视觉验证连续热更新外观设置后，恢复 `config.json` 时出现 `config.json.tmp -> config.json` 权限拒绝。
    - 根因：Windows 上目标文件可能被另一个运行中进程、文件观察器或安全扫描短暂占用；一次性 `Path.replace()` 失败后旧逻辑只记录警告，容易造成“界面已更新但配置未落盘”的错觉。
    - 修复：`ConfigManager.save()` 写入同目录临时文件后执行原子替换；遇到 `PermissionError` 会短重试并清理临时文件，定点测试模拟首轮锁冲突后第二轮保存成功。
    - 经验：热加载配置不仅要验证 UI 立即生效，也要验证落盘可靠性；Windows 文件替换最好按“短暂竞争”设计，而不是把权限错误当作不可恢复异常。

## 新约束

- 除下载目录和 MissAV 自定义代理端点外，设置项必须使用下拉、开关或分段按钮。
- `speed_limit_kb=0` 必须显示为“无限制（0 KB/s）”。
- 平台默认数量必须带单位，例如短视频平台“20 个视频（推荐）”、分页平台“1 页（推荐）”。
- 外观设置包含语言选项，支持 `zh-CN`、`en-US`、`zh-TW`，GUI 和 WebUI 使用同一快照字段。
- GUI 和 WebUI 都从 `FrontendStateService.settings_snapshot()` 读取同一组选项。
- GUI 与 WebUI 配置中心都采用“左侧分类 + 右侧详情”的 master-detail 布局；平台设置使用摘要条和稳定表格列。
- WebUI 不再生成 `type="number"` 设置控件。
- WebUI 首页与 CSS/JS 静态资源必须通过真实 `create_app()` 路径返回禁缓存头，避免升级后仍显示旧页面。
