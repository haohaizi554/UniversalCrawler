# 截图与提交材料清单

本清单用于帮助整理课程大作业的电子版与纸质版材料，建议边执行边打勾。

## 1. 报告基础信息

- [ ] 报告封面
- [ ] 学号、姓名、班级、课程名称、教师姓名
- [ ] 项目名称与项目简介
- [ ] 测试环境说明

## 2. 黑盒测试截图

建议至少准备以下截图：

- [ ] 文件名清洗类测试结果截图
- [ ] 配置损坏恢复测试结果截图
- [ ] 控制器删除失败分支测试结果截图
- [ ] B 站无音频分支解析测试结果截图
- [ ] 抖音无效 payload 返回 `None` 的测试结果截图

推荐截图来源：

- `python -m unittest tests.test_utils_filenames`
- `python -m unittest tests.test_config_settings`
- `python -m unittest tests.test_application_controller`
- `python -m unittest tests.test_spider_helpers`

## 3. 白盒测试截图

建议至少准备以下截图：

- [ ] `runtime_paths` 冻结环境路径分支截图
- [ ] `main.main()` 正常启动分支截图
- [ ] `main.main()` 启动失败分支截图
- [ ] `DownloadManager._dispatch_loop()` 正常派发分支截图
- [ ] `DownloadManager._dispatch_loop()` 调度失败分支截图

推荐截图来源：

- `python -m unittest tests.test_runtime_paths`
- `python -m unittest tests.test_main_entry`
- `python -m unittest tests.test_download_manager_dispatch`

## 4. 接口集成测试截图

本项目为桌面应用，建议将内部模块间调用链视为接口进行展示。

- [ ] `Parser -> Controller -> DownloadManager` 链路截图
- [ ] `Spider.emit_video() -> Controller` 链路截图
- [ ] `DownloadWorker` 生命周期与扩展名修正截图
- [ ] 配置持久化回读一致性截图
- [ ] Cookie 保存与回读一致性截图

推荐截图来源：

- `python -m unittest tests.test_integration_flows`
- `python -m unittest tests.test_config_settings`
- `python -m unittest tests.test_auth_service`

## 5. UI 测试截图

自动化 UI 结果：

- [ ] 主题切换测试通过截图
- [ ] 全屏恢复测试通过截图
- [ ] 下载队列表格状态刷新测试通过截图

人工 UI 验收建议补图：

- [ ] 启动主界面截图
- [ ] 平台切换截图
- [ ] 更换保存目录截图
- [ ] 下载队列进度截图
- [ ] 媒体预览或播放截图

推荐截图来源：

- `python -m unittest tests.test_main_window`
- `python -m unittest tests.test_download_queue_panel`
- 真实运行 `python main.py`

## 6. 批量测试套件截图

- [ ] `python tests/run_core_suite.py` 命令与通过结果截图
- [ ] `python -m unittest discover -s tests` 命令与通过结果截图

建议截图中包含：

- 运行命令
- 通过数量
- `OK` 结果

## 7. 真实场景验收截图

可使用根目录 `测试案例.txt` 中的数据完成：

### 抖音

- [ ] 输入分享链接截图
- [ ] 解析结果列表截图
- [ ] 下载成功后文件落盘截图

### Bilibili

- [ ] 输入 BV 号截图
- [ ] 空间扫描或合集扫描截图
- [ ] DASH 下载与合并成功截图

### 快手

- [ ] 登录或主页访问截图
- [ ] 页面滚动与结果出现截图
- [ ] 捕获任务进入列表截图

### MissAV

- [ ] 输入番号截图
- [ ] 列表命中截图
- [ ] m3u8 下载结果截图

## 8. 打包与交付截图

- [ ] 绿色版目录截图
- [ ] 安装版安装界面截图
- [ ] 绿色版启动成功截图
- [ ] 安装版启动成功截图
- [ ] `dist/UniversalCrawlerPro/BUILD_INFO.txt` 截图

## 9. 建议文件命名

为方便报告排版，建议统一按如下规则保存截图：

```text
01-黑盒-文件名清洗.png
02-白盒-runtime_paths-frozen分支.png
03-接口集成-parser-controller-queue.png
04-UI-主题切换.png
05-批量套件-run_core_suite.png
06-验收-抖音分享链接.png
07-打包-绿色版目录.png
```

## 10. 最终提交清单

- [ ] 报告 Word 版
- [ ] 报告 PDF 版
- [ ] 测试用例 Excel 版
- [ ] 课程相关源码与测试脚本
- [ ] 关键运行结果截图
- [ ] 项目说明与测试说明文档
- [ ] 最终压缩包已按“学号+姓名+班级”命名
