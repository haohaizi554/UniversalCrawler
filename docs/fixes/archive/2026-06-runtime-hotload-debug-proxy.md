# 运行时热加载与调试日志代理修复

## 现象

全量测试中暴露了两个和运行时体验相关的隐蔽问题：

1. 更新下载设置时，`max_concurrent` 已经通过运行中的下载管理器生效，但后续兜底同步又用旧配置值调用了一次运行时 setter，导致并发数被回退。
2. 测试通过 `patch("app.debug_logger.debug_logger.configure")` 临时替换日志配置方法后，退出 patch 上下文时无法恢复属性，原因是 `DebugLoggerProxy` 支持 `__getattr__` / `__setattr__`，但缺少 `__delattr__`。

## 根因

热加载路径同时承担了两类职责：持久化配置和同步运行时对象。旧实现把“读取配置兜底”和“重新应用运行时值”混在一起，当 mock 配置对象只暴露 `data` 而 `get()` 仍返回默认值时，后续同步会读到旧默认值。

日志代理的问题属于 Python 代理对象协议不完整。`unittest.mock.patch` 恢复被替换属性时可能调用 `delattr()`，代理对象没有转发删除行为，就会在测试清理阶段失败。

## 修复

- 为 `FrontendStateService` 增加 `_config_section_values()`，优先读取测试和运行时都能共享的 section 数据。
- `_apply_download_runtime_settings()` 只通过完整的 `set_runtime_options()` 同步运行态，不再额外兜底调用 `set_max_concurrent()`。
- `DebugLoggerProxy` 增加 `__delattr__()`，让 mock patch 可以完整进入和退出。

## 经验

运行时热加载最好保持单一写入路径：一次 action 里可以先持久化，再调用一个明确的运行态同步方法，但不要在不同方法里重复写同一个运行时字段。代理对象如果用于模块级全局实例，也要覆盖测试工具会用到的属性生命周期方法，包括设置和删除。

## 相关文件

- `app/services/frontend_state_service.py`
- `app/debug_logger.py`
- `tests/test_frontend_state_service.py`
