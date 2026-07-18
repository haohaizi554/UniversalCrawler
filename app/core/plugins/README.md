# 插件模块说明

`app/core/plugins/` 负责把平台能力注册为统一的 UI 与运行时入口。

## 主要职责

- 定义平台插件对象
- 暴露平台名称、搜索提示与配置面板
- 返回对应 spider 类
- 收集每个平台的运行配置

## 关键文件

- `definitions.py`
  - 默认平台插件定义。
- `settings_builders.py`
  - 各平台设置控件构建与读取。
- `registry.py`
  - 实际注册表实现。

## 设计要求

- 控制器只依赖注册表，不直接硬编码平台实现。
- 新平台接入时，优先通过插件注册而不是在 UI 中加分支。
- 平台配置项变化后，要同步维护读取逻辑与默认值。
- 平台交互、鉴权和确认摘要通过 `interactive_spec` 声明，宿主不得按平台
  ID 复制一份分支。

## 外部插件交互清单

未声明 `interactive_spec` 的插件仍可正常运行，并会得到基于
`get_search_placeholder()` 的通用引导。通用清单不会从
`get_default_config()` 猜测字段，避免把 Cookie、token 或插件私有配置暴露到
终端。

需要完整引导时，可在插件类中声明宿主无关的强类型元数据：

```python
from app.core.plugins import (
    BasePlugin,
    InteractiveChoice,
    InteractiveField,
    PlatformAuthSpec,
    PlatformInteractiveSpec,
)


class ExamplePlugin(BasePlugin):
    id = "example"
    name = "Example"
    aliases = ("ex",)
    interactive_spec = PlatformInteractiveSpec(
        input_label="输入 Example 作品链接或关键词",
        examples=("https://example.test/item/123",),
        empty_tip="请检查输入和 Example 登录状态。",
        result_tip="Example 将使用插件解析器获取作品。",
        fields=(
            InteractiveField(
                key="max_items",
                prompt="作品数量",
                summary_label="数量",
                choices=(
                    InteractiveChoice("5", 5),
                    InteractiveChoice("20", 20),
                ),
            ),
        ),
        auth=PlatformAuthSpec(
            mode="cookie",
            config_key="example_cookie_file",
            default_file="example_auth.json",
            cookie_names=("session",),
            login_url="https://example.test/",
            login_description="请在 Example 浏览器窗口中登录。",
            summary="浏览器登录",
        ),
    )
```

SDK 与 Web API 的平台清单会公开 JSON-safe 的 `interactive` 字段；CLI
interactive 直接使用该字段构建引导、菜单、Cookie 预检和确认摘要。插件元数据
层不得导入 Qt、argparse、终端颜色或 Web 类型。

## 分支维护说明

当前分支重点是让测试、文档和注册入口保持一致，因此修改平台注册相关逻辑后，请同步更新：

- `docs/guides/api.md`
- `docs/guides/development.md`
- 根目录 `README.md`
