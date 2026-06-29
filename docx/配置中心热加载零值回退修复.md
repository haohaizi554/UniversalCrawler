# 配置中心热加载零值回退修复

## 背景

配置中心新增下载、播放、日志、外观等分组后，GUI 和 WebUI 都通过 `FrontendStateService.handle_action("update_setting", payload)` 热加载设置。回归测试覆盖 `download.max_retries=0` 时发现快照仍显示为 `3`。

## 现象

用户把重试次数设为 `0`，期望表示“不自动重试”。服务端动作返回成功，但 `settings_snapshot()["下载设置"]["max_retries"]` 仍回到默认值 `3`，刷新后 GUI/WebUI 都会显示错误值。

## 根因

更新下载选项时使用了：

```python
int(data.get("max_retries") or self.config.get("download", "max_retries", 3))
```

`0` 在 Python 中是 falsy，因此被 `or` 当成未传值，直接回退到旧配置或默认值。

## 修复

改为显式区分“字段不存在”和“字段存在但值为 0”：

```python
int(data.get("max_retries", self.config.get("download", "max_retries", 3)))
```

同时补充回归测试：

- `tests/test_frontend_state_service.py::test_update_setting_hot_loads_extended_sections_and_persists`
- `tests/test_config_settings.py::test_extended_ui_sections_persist_with_normalized_types`

## 经验

允许 `0`、空字符串或 `False` 作为合法业务值的字段，不能使用 `value or default`。配置层和前端动作层应统一采用显式缺省判断。
