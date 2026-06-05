# AI Skill 封装指南

UCrawl 提供了符合 Claude / LLM skill 规范的封装，让 LLM 可以直接调用爬虫。

## Skill 信息

- **Skill 位置**：`cli/skill/SKILL.md` 和 `.trae/skills/ucrawl/SKILL.md`
- **Skill 入口**：`cli/skill/ucrawl_skill.py`
- **激活方式**：在 LLM 提示中提到 "ucrawl" 或 "爬虫" 即可激活

## Skill 描述

```
name: "ucrawl"
description: "通用视频爬虫工具 (CLI / SDK / REST API / AI Skill)。
支持抖音/B站/快手/MissAV 四平台，可通过 CLI 命令、Python 函数、
web 服务启动时注入脚本三种方式调用，并能处理合集/多用户的二次选择场景。
Invoke when user wants to search/download videos from these platforms,
batch crawl, integrate crawler into existing service, or call crawler from LLM/script."
```

## LLM 调用流程

1. 用户在对话中提到 "ucrawl" 或 "搜索抖音视频"
2. LLM 看到 SKILL.md 的 description，激活 skill
3. LLM 读取 SKILL.md 详细说明
4. LLM 调用 CLI 命令
5. 解析返回的 JSON，给用户友好回复

## 调用示例

### 示例 1：搜索视频

```
User: 帮我搜索抖音上"测试"关键词的 10 个视频
LLM: 激活 ucrawl skill
LLM: 执行 `python -m cli search --source douyin --keyword "测试" --max-items 10`
LLM: 找到以下视频：[返回结果]
```

### 示例 2：下载 B 站合集

```
User: 下载 B 站 BV1xxx 合集的前 5 个视频
LLM: 激活 ucrawl skill
LLM: 执行 `python -m cli search --source bilibili --keyword "BV1xxx" --select "0,1,2,3,4"`
LLM: 正在下载... 已完成 [视频列表]
```

### 示例 3：AI 自动化任务

```python
# AI 可以生成自动化脚本
script_content = """
def main(controller, **kwargs):
    from cli import UcrawlSDK
    sdk = UcrawlSDK(save_dir=controller.current_save_dir)
    
    # 搜索并下载
    result = sdk.search(
        kwargs.get("source", "douyin"),
        kwargs.get("keyword", ""),
        max_items=int(kwargs.get("max", 10)),
        selection="all"
    )
    
    return {"count": len(result["items"]), "status": "ok"}
"""
```

## 参数传递

LLM 调用时可以传递以下参数：

| 参数 | 说明 | 示例 |
|---|---|---|
| `source` | 平台 ID | `douyin`, `bilibili`, `kuaishou`, `missav` |
| `keyword` | 搜索关键词 | `测试`, `BV1xxx`, `ABC-123` |
| `max-items` | 最大视频数 | `10`, `20`, `50` |
| `selection` | 选择策略 | `all`, `first`, `0,2,5` |

## 返回结果

```json
{
  "status": "ok",
  "source": "douyin",
  "keyword": "测试",
  "items": [
    {
      "id": "v_abc123",
      "url": "https://...",
      "title": "视频标题",
      "status": "✅ 完成",
      "progress": 100,
      "local_path": "/path/to/file.mp4"
    }
  ],
  "elapsed": 12.34
}
```

## 二次选择

当遇到合集或多用户时，LLM 需要处理二次选择：

1. 爬虫返回需要选择的信息
2. LLM 根据上下文决定选择
3. 使用 `--select` 参数指定选择

```bash
# 选择第 0, 2, 5 项
python -m cli search --source bilibili --keyword "BV1xxx" --select "0,2,5"

# 合集场景：预加载多轮选择
python -m cli search --source bilibili --keyword "BV1xxx" --preload-choices "0|1,2|3"
```

## 错误处理

| 错误 | 原因 | 解决 |
|---|---|---|
| `PyQt6 未安装` | 缺少依赖 | 安装 PyQt6 |
| `proxy error` | 代理不可用 | 改用 `--proxy` 或关闭代理 |
| `timeout` | 网络慢或平台限流 | 重试或加大超时 |
| `二次选择策略异常` | 选择器逻辑错误 | 用 `--all` 兜底 |
