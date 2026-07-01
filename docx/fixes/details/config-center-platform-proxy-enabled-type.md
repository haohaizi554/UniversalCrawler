# 配置中心平台代理启用状态类型修复

## 现象

运行 GUI smoke test，进入配置中心并切换到“平台设置”分组时，界面渲染中断并抛出异常：

```text
TypeError: setEnabled(self, a0: bool): argument 1 has unexpected type 'str'
```

## 复现步骤

1. 启动 `QApplication` 和 `MainWindow`。
2. 打开配置中心。
3. 依次切换配置中心分组。
4. 切换到平台设置时触发异常。

## 根因分析

平台代理下拉框的启用状态使用了下面的表达式：

```python
editable = bool(row.get("proxy_editable", policy.get("editable"))) and platform_id and config_key
```

Python 的 `and` 会返回最后一个参与运算的真值对象。当前平台可编辑且存在 `config_key` 时，`editable` 最终变成配置字段名字符串，而不是 `bool`。

Qt 的 `QWidget.setEnabled()` 不接受字符串，因此平台设置分组无法渲染。

## 错误代码 / 日志

```text
File "app/ui/pages/settings_page.py", line 1215, in _platform_proxy_combo
    proxy_combo.setEnabled(editable)
TypeError: setEnabled(self, a0: bool): argument 1 has unexpected type 'str'
```

## 修复方案

把整个启用条件包进 `bool()`：

```python
editable = bool(row.get("proxy_editable", policy.get("editable")) and platform_id and config_key)
```

并新增 GUI 契约测试，直接切换到平台设置分组，验证代理下拉框可以正常渲染且 `isEnabled()` 返回布尔值。

## 为什么这样修

这里需要的是严格布尔开关，而不是“可 truthy 判断”的业务值。将完整表达式转成 `bool` 可以同时保留原有启用条件，并满足 Qt API 的类型要求。

## 如何避免再次发生

涉及 Qt API 的 enabled / checked / visible / expanded 等状态值时，不使用链式 `and` 的返回值直接传入 API；应显式转成 `bool`，并补充运行时 GUI smoke 或控件渲染测试。

## 相关文件

- `app/ui/pages/settings_page.py`
- `tests/test_unified_frontend_contract.py`
- `runtime_artifacts/baseline-gui/gui-smoke-result.json`
