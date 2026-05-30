# 今日截图补充顺序清单

这份清单按“最省时间、最容易拿到结果、最适合写进报告”的顺序安排，建议照着执行。

## 第一阶段：先拿自动化结果图

这一阶段最稳，几乎不依赖外部网络。

### 1. 全量测试结果

执行：

```bash
python -m unittest discover -s tests
```

截图要求：

- 命令行中包含完整命令
- 显示 `Ran 211 tests`
- 显示 `OK`

建议命名：

- `01-全量回归-discover.png`

### 2. 核心套件结果

执行：

```bash
python tests/run_core_suite.py
```

截图要求：

- 命令行中包含完整命令
- 显示 `Ran 175 tests`
- 显示 `OK`

建议命名：

- `02-核心套件-run_core_suite.png`

### 3. 黑盒代表用例

依次执行：

```bash
python -m unittest tests.test_utils_filenames
python -m unittest tests.test_config_settings
python -m unittest tests.test_application_controller
```

建议各截一张图，分别对应：

- 文件名清洗
- 配置损坏恢复
- 删除失败分支

建议命名：

- `03-黑盒-文件名清洗.png`
- `04-黑盒-配置损坏恢复.png`
- `05-黑盒-删除失败分支.png`

### 4. 白盒代表用例

依次执行：

```bash
python -m unittest tests.test_runtime_paths
python -m unittest tests.test_main_entry
python -m unittest tests.test_download_manager_dispatch
```

建议命名：

- `06-白盒-runtime_paths.png`
- `07-白盒-main入口.png`
- `08-白盒-download_manager_dispatch.png`

---

## 第二阶段：补接口集成与 UI 图

### 5. 接口集成链路

执行：

```bash
python -m unittest tests.test_integration_flows
```

这一组截图最适合写“接口测试”或“集成测试”部分。

建议命名：

- `09-接口集成-parser-controller-queue.png`
- `10-接口集成-downloadworker-lifecycle.png`

### 6. UI 自动化结果

执行：

```bash
python -m unittest tests.test_main_window
python -m unittest tests.test_download_queue_panel
```

建议命名：

- `11-UI-主题切换与全屏恢复.png`
- `12-UI-下载队列表格刷新.png`

---

## 第三阶段：真实运行截图

这一阶段可能耗时稍长，但最能体现作业完整度。

### 7. 启动主界面

执行：

```bash
python main.py
```

截图内容：

- 主界面整体
- 平台选择区
- 下载列表区
- 日志区

建议命名：

- `13-主界面-首页.png`

### 8. UI 交互截图

在程序中完成：

- 切换平台
- 切换保存目录
- 展示下载队列
- 打开日志或错误摘要

建议命名：

- `14-UI-平台切换.png`
- `15-UI-目录切换.png`
- `16-UI-日志入口.png`

---

## 第四阶段：真实业务验收截图

建议只选 2 到 3 个最稳定的平台流程，不一定全部都做满。

### 9. 推荐优先顺序

优先顺序建议：

1. Bilibili BV 流程
2. 抖音分享链接流程
3. MissAV 番号流程
4. 快手主页流程

原因：

- B 站和抖音更适合展示“输入 -> 解析 -> 入队”
- MissAV 更适合展示“代理 + m3u8 下载”
- 快手依赖浏览器动态行为，波动稍大，建议放后面

### 10. 验收截图最少集

每个平台至少保留三类截图：

- 输入截图
- 结果列表截图
- 成功入队或下载完成截图

建议命名：

- `17-验收-B站-BV输入.png`
- `18-验收-B站-结果列表.png`
- `19-验收-B站-入队成功.png`
- `20-验收-抖音-分享链接.png`
- `21-验收-抖音-结果列表.png`
- `22-验收-抖音-下载完成.png`

---

## 第五阶段：交付与打包截图

### 11. 打包结果

建议保留：

- `dist/UniversalCrawlerPro` 目录截图
- 安装包文件截图
- `BUILD_INFO.txt` 截图

建议命名：

- `23-打包-绿色版目录.png`
- `24-打包-安装版文件.png`
- `25-打包-BUILD_INFO.png`

### 12. 产物启动

建议各来一张：

- 绿色版启动成功
- 安装版启动成功

建议命名：

- `26-打包-绿色版启动.png`
- `27-打包-安装版启动.png`

---

## 最终建议

如果今天时间有限，优先完成这 8 张：

1. `01-全量回归-discover.png`
2. `02-核心套件-run_core_suite.png`
3. `03-黑盒-文件名清洗.png`
4. `06-白盒-runtime_paths.png`
5. `09-接口集成-parser-controller-queue.png`
6. `11-UI-主题切换与全屏恢复.png`
7. `13-主界面-首页.png`
8. `23-打包-绿色版目录.png`

这 8 张已经足够把报告主体撑起来。
