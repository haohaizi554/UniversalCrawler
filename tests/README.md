# 测试目录说明

当前分支已把 `tests/` 从零散回归检查继续补到覆盖核心风险路径的方向。

## 当前覆盖重点

- 配置、服务与数据模型
- 控制器编排与 UI 交互边界
- 下载器选择、落盘路径、扩展名修正
- B 站取流回退、快手流捕获、MissAV 列表扫描
- 抖音输入分流、图集拆分与兼容行为

## 运行方式

```bash
python -m unittest discover -s tests
```

## 编写约定

- 继续使用 `unittest`。
- 优先写稳定的单元测试和半集成测试。
- 浏览器相关逻辑优先 mock `page / context / response`。
- 高风险改动同步补测试，不把测试留到最后。

## 推荐文件划分

- `test_spider_helpers.py`
  - 平台 spider、parser、task_builder、API 辅助逻辑。
- `test_downloaders.py`
  - 下载器、下载管理器和 DownloadWorker。
- `test_application_controller.py`
  - 控制器与 UI/下载器衔接。

## 分支维护建议

新增平台或重构目录时，请同步更新本文件与 `docs/testing.md`。
