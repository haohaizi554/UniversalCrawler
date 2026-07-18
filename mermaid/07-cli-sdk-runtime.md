# 07 CLI / SDK / Shared Runtime

## 当前包边界与调用方向

```mermaid
flowchart TB
    subgraph Entry["入口层"]
        CLIEntry["entry/cli_entry.py"]
        InteractiveEntry["entry/interactive_entry.py"]
        WebEntry["entry/web_entry.py"]
    end

    subgraph CLI["cli/ 命令宿主"]
        Main["cli/main.py<br/>根解析器与分发"]
        CmdSearch["cli/commands/search.py"]
        CmdDownload["cli/commands/download.py"]
        CmdScan["cli/commands/scan.py"]
        CmdPlatforms["cli/commands/platforms.py"]
        CmdInteractive["cli/commands/interactive.py"]
        InteractiveFlow["cli/interactive/"]
        CLIInit["cli/__init__.py<br/>仅 shared.version"]
    end

    subgraph PublicSDK["公开 Python 包"]
        SDKInit["ucrawl/__init__.py"]
    end

    subgraph Shared["shared/ 中立运行时"]
        SearchRt["shared.search_command_runtime"]
        DownloadRt["shared.download_command_runtime"]
        ScanRt["shared.scan_command_runtime"]
        SDKRt["shared.sdk_runtime"]
        RunnerRt["shared.cli_runner_runtime"]
        SelectionRt["shared selection runtimes"]
        Version["shared.version"]
    end

    subgraph Plugins["插件契约"]
        Manifest["plugin manifest<br/>identity + aliases + interactive"]
        PluginRuntime["Spider / Plugin runtime"]
    end

    subgraph Web["Web 专属边界"]
        ScriptAPI["app.web.script_api<br/>Web --script"]
        InjectedScript["用户注入脚本"]
    end

    CLIEntry --> Main
    InteractiveEntry --> CmdInteractive
    WebEntry --> ScriptAPI --> InjectedScript

    Main --> CmdSearch --> SearchRt
    Main --> CmdDownload --> DownloadRt
    Main --> CmdScan --> ScanRt
    Main --> CmdPlatforms --> SDKRt
    Main --> CmdInteractive --> InteractiveFlow

    InteractiveFlow --> Manifest
    InteractiveFlow --> SDKRt
    InteractiveFlow --> RunnerRt
    InteractiveFlow --> SelectionRt

    SearchRt --> RunnerRt
    DownloadRt --> SDKRt
    ScanRt --> SDKRt
    SDKRt --> RunnerRt
    SDKRt --> Manifest
    RunnerRt --> PluginRuntime

    SDKInit --> SDKRt
    SDKInit --> RunnerRt
    SDKInit --> SelectionRt
    CLIInit --> Version

    Manifest --> PluginRuntime

    style CLI fill:#fff3e0,color:#e65100
    style Shared fill:#bbdefb,color:#0d47a1
    style Plugins fill:#c8e6c9,color:#1a5e20
    style PublicSDK fill:#f3e5f5,color:#6a1b9a
```

`cli` 是命令实现包，不再充当 SDK 再导出层。公共 SDK、runner 与选择策略
统一从 `ucrawl/__init__.py` 导入。`ucrawl platforms` 与交互引导读取同一份
plugin manifest；外部插件可在 manifest 的 `interactive` 字段声明输入提示、
选项字段和鉴权元数据。

## 命令分发与语义运行时

```mermaid
flowchart LR
    Main["cli.main"] --> Dispatch{"子命令"}

    Dispatch -->|search| SearchHost["search host"]
    Dispatch -->|download| DownloadHost["download host"]
    Dispatch -->|scan| ScanHost["scan host"]
    Dispatch -->|platforms| PlatformsHost["platforms host"]
    Dispatch -->|interactive| InteractiveHost["interactive host"]

    SearchHost --> SearchRt["shared.search_command_runtime"]
    DownloadHost --> DownloadRt["shared.download_command_runtime"]
    ScanHost --> ScanRt["shared.scan_command_runtime"]
    PlatformsHost --> SDKRt["shared.sdk_runtime"]
    InteractiveHost --> InteractiveFlow["manifest-driven interactive flow"]

    SearchRt --> Runner["shared.cli_runner_runtime"]
    DownloadRt --> SDKRt
    ScanRt --> SDKRt
    InteractiveFlow --> SDKRt
    InteractiveFlow --> Runner
    InteractiveFlow --> Selection["shared selection runtimes"]

    Runner --> Plugin["Spider / Plugin"]
```

三个命令运行时都返回语义状态，再由 CLI 宿主统一映射为稳定退出码。scan
的参数校验、SDK 生命周期和结果输出属于 `shared.scan_command_runtime`，
`cli/commands/scan.py` 只装配配置依赖。

## 共享选择策略

```mermaid
classDiagram
    class SelectionStrategyFactory {
        +from_value(value)
        +from_cli_args(args)
    }

    class SelectionBridge {
        +select(items, config)
    }

    class AutoSelection
    class RuleSelection
    class InteractiveTTYSelection
    class PipeSelection

    SelectionStrategyFactory --> SelectionBridge
    SelectionBridge --> AutoSelection
    SelectionBridge --> RuleSelection
    SelectionBridge --> InteractiveTTYSelection
    SelectionBridge --> PipeSelection
```

桌面 GUI 的选择策略属于 `app.ui`，不从 CLI 或公共 SDK 包导出。

## SDK API（shared/sdk_runtime.py）

```mermaid
flowchart TB
    subgraph SDK["UcrawlSDK"]
        Init["__init__(config, save_dir, verbose)"]
        Search["search(source, keyword, **opts)<br/>→ structured result dict"]
        Download["download_video(url, source, **opts)<br/>→ structured result dict"]
        Platforms["list_platforms()<br/>→ list[plugin manifest]"]
        Scan["scan_directory(directory, scan_limit)<br/>→ structured result dict"]
        Close["close()<br/>清理资源"]
    end

    SDKRt["shared.sdk_runtime"]
    Runner["shared.cli_runner_runtime"]
    Manifest["plugin manifest"]

    Init --> SDKRt
    Search --> SDKRt --> Runner
    Download --> SDKRt
    Platforms --> SDKRt --> Manifest
    Scan --> SDKRt
    Close --> SDKRt
```

## AI Skill 集成

```mermaid
flowchart LR
    SkillMD["cli/skill/SKILL.md"] --> Wrapper["ucrawl_skill.py"]
    Wrapper --> Public["ucrawl/__init__.py"]
    Public --> SDK["shared.sdk_runtime"]
```
