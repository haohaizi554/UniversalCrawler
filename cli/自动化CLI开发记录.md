# 自动化 CLI 开发记录

本文档记录 CLI / SDK / REST API / WebSocket / Skill 五层与 GUI 输入输出对齐的开发历史。

---

## 第46轮：BilibiliSpider emit_video 补全 content_type + SDK bilibili cookies dict 自动加载（2026-06-07）

### 检查范围

对比 CLI/SDK/API/Skill 层与成熟 GUI（各平台 spider）在下载 meta 字段设置上的差异，重点关注：
1. BilibiliSpider `emit_video` 的 meta dict 是否设置了 `content_type`（与 DouyinParser 对齐）
2. SDK `get_platform_download_defaults` 是否为 bilibili 加载 `cookies` dict（与 BilibiliSpider 对齐）

### 发现的差异

1. **BilibiliSpider `emit_video` 缺少 `content_type: "video"`（高优先级）**：
   - DouyinParser 在 `parse_aweme` 中始终设置 `"content_type": "video"`（line 63）
   - BilibiliSpider 在 `emit_video` 的 meta dict 中未设置 `content_type`
   - `DownloadWorker._infer_extension` 读取 `video_item.meta.get("content_type")` 推断文件扩展名
   - 缺少 `content_type` 时 `_infer_extension` 依赖 fallback 逻辑，可能导致扩展名推断不准确
   - GUI 流程中 BilibiliSpider 的 meta 不含 `content_type`，但下载器有 fallback 兜底，影响较小
   - CLI/SDK/API 通过 spider 搜索后下载时，meta 同样缺少 `content_type`，行为与 GUI 一致但不够健壮

2. **SDK `get_platform_download_defaults` 未为 bilibili 加载 `cookies` dict**：
   - BilibiliSpider 通过 `self.api.sess.cookies` 获取 cookie dict 并设置到 `meta["cookies"]`
   - BilibiliDownloader 优先读取 `cookies` dict（而非 `cookie` string）用于刷新 CDN URL
   - SDK `get_platform_download_defaults` 只加载 `cookie` string（通过 `_try_load_cookie`），不加载 `cookies` dict
   - CLI/SDK 直接下载 B站视频时，BilibiliDownloader 无法使用 `cookies` dict 刷新 CDN URL，可能导致下载失败

### 修复内容

#### 修复1：BilibiliSpider `emit_video` 补全 `content_type: "video"`

**文件**：`app/spiders/bilibili/spider.py`

- 在 `emit_video` 的 meta dict 中新增 `"content_type": "video"`
- 与 DouyinParser 的 `parse_aweme` 对齐，确保 `DownloadWorker._infer_extension` 能正确推断文件扩展名
- 位置：`trace_id` 之后，`audio_url` 之前

```python
meta = {
    "trace_id": task["trace_id"],
    "content_type": "video",  # 新增：与 DouyinParser 对齐
    "audio_url": a_url,
    ...
}
```

#### 修复2：SDK `get_platform_download_defaults` 为 bilibili 加载 `cookies` dict

**文件**：`cli/defaults.py`

- 新增 `_try_load_cookies_dict(source)` 辅助函数：
  - 加载本地 auth JSON 文件（与 `_try_load_cookie` 使用相同的文件查找路径）
  - 支持 dict 格式（直接 name→value 映射）和 list 格式（每个元素含 name/value 字段）
  - 返回 `dict | None`
- 在 `get_platform_download_defaults` 中，当 `source == "bilibili"` 时额外调用 `_try_load_cookies_dict`
  - 如果加载成功，设置 `result["cookies"]`
  - 与 BilibiliSpider 通过 `self.api.sess.cookies` 设置 `cookies` dict 的行为对齐
  - 确保 BilibiliDownloader 能使用 `cookies` dict 刷新 CDN URL

### 对齐验证

| 层 | BilibiliSpider content_type | SDK bilibili cookies dict |
|---|---|---|
| GUI spider | ✅ `"content_type": "video"` | ✅ `self.api.sess.cookies` |
| CLI search | ✅ spider 设置 | ✅ spider 设置 |
| CLI download | N/A（直接下载） | ✅ `get_platform_download_defaults` 自动加载 |
| SDK download_video | N/A（直接下载） | ✅ `get_platform_download_defaults` 自动加载 |
| REST API download | N/A（直接下载） | ✅ SDK 内部合并 |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1 只在 BilibiliSpider 的 `emit_video` meta dict 中新增一个字段，GUI 下载器已有 fallback 兜底，行为不变
2. 修复2 只在 `cli/defaults.py` 中新增辅助函数和条件分支，GUI 不使用 `get_platform_download_defaults`
3. `ApplicationController` 未修改
4. `WebController` 未修改
5. `server.py` 未修改
6. CLIRunner 未修改
7. 所有下载器未修改（只是确保 SDK 传入的 meta 字段能被下载器正确读取）

---

## 第45轮：SDK download_video meta 字段补全 duration/mix_title/create_time/author/has_live_photo + SKILL.md 通用下载参数补全（2026-06-07）

### 检查范围

全面对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController / 各平台 spider / 下载器）在输入输出上的差异，重点关注：
1. GUI spider `DouyinParser.parse_aweme` 设置的 meta 字段是否全部被 SDK `download_video` meta 复制列表覆盖
2. GUI 下载器（ChunkedDownloader / FFmpegDownloader）读取的 meta 字段是否全部被 SDK 覆盖
3. `validate_config_types` 是否覆盖所有 SDK meta 复制列表中的字段
4. interactive 命令的 `download_config` 提取列表是否与 SDK meta 复制列表完全对齐
5. SKILL.md 通用下载参数是否完整

### 发现的差异

1. **`duration` 字段缺失（高优先级）**：
   - GUI spider `DouyinParser.parse_aweme` 设置 `duration`（视频时长秒数，line 69）
   - `ChunkedDownloader` 读取 `video_item.meta.get("duration", 0)` 决定下载策略（line 29）
   - `FFmpegDownloader` 读取 `video_item.meta.get("duration", 0)` 决定下载策略（line 34）
   - SDK `download_video` meta 复制列表未包含 `duration`
   - `validate_config_types` 未包含 `duration`
   - interactive 命令 `download_config` 提取列表未包含 `duration`
   - SKILL.md 通用下载参数未记录 `duration`

2. **`mix_title` 字段缺失**：
   - GUI spider `DouyinSpider._process_mix` 设置 `item.meta['mix_title']`（line 610）
   - SDK/validate/interactive/SKILL.md 均未覆盖

3. **`create_time` 字段缺失**：
   - GUI spider `DouyinParser.parse_aweme` 设置 `create_time`（line 66）
   - SDK/validate/interactive/SKILL.md 均未覆盖

4. **`author` 字段缺失**：
   - GUI spider `DouyinParser.parse_aweme` 设置 `author`（line 67），用作 `folder_name`
   - SDK/validate/interactive/SKILL.md 均未覆盖

5. **`has_live_photo` 字段缺失**：
   - GUI spider `DouyinParser.parse_aweme` 设置 `has_live_photo`（line 80）
   - SDK/validate/interactive/SKILL.md 均未覆盖

6. **SKILL.md 通用下载参数不完整**：
   - 缺少 `duration`、`file_name`、`preferred_filename`、`mix_title`、`create_time`、`author`、`has_live_photo`
   - `file_name` 和 `preferred_filename` 仅在 B站平台参数中列出，未归入通用下载参数

### 修复内容

1. **`cli/sdk.py`**：SDK `download_video` meta 复制列表新增 `duration`、`mix_title`、`create_time`、`author`、`has_live_photo` 五个字段
2. **`cli/defaults.py`**：`validate_config_types` 新增这五个字段的类型校验（`duration`: int/float, `mix_title`: str, `create_time`: int, `author`: str, `has_live_photo`: bool）
3. **`cli/commands/interactive.py`**：`download_config` 提取列表同步扩展，新增这五个字段
4. **`cli/skill/SKILL.md`**：
   - 通用下载参数新增 `duration`、`file_name`、`preferred_filename`、`mix_title`、`create_time`、`author`、`has_live_photo`
   - 注意事项新增 `duration/mix_title/create_time/author/has_live_photo` 字段补全说明

### 影响范围

- **纯增量修改**，不影响原有桌面 GUI 和 WebUI
- 新增字段均为可选字段，不传则不影响下载行为
- `duration` 字段对 ChunkedDownloader/FFmpegDownloader 的下载策略选择有实际影响，用户可通过 `config={"duration": 120}` 传入

---

## 第44轮：CLI 命令 --content-type 便捷参数补全 + validate_config_types content_type 校验（2026-06-07）

### 检查范围

全面对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController）在输入输出上的差异，重点关注：
1. CLI 命令（search/download/interactive）便捷参数是否覆盖所有 GUI spider `build_download_meta` 设置的关键字段
2. `validate_config_types` 是否覆盖所有 SDK meta 复制列表中的字段
3. SKILL.md 文档是否与代码一致

### 发现的差异

1. **`validate_config_types` 缺少 `content_type` 类型校验**：
   - SDK `download_video` meta 复制列表包含 `content_type`
   - `DownloadWorker._infer_extension` 读取 `video_item.meta.get("content_type")` 推断文件扩展名
   - `DownloadWorker._resolve_save_dir` 读取 `video_item.meta.get("content_type")` 决定图集保存路径
   - `validate_config_types` 不包含 `content_type`，用户传入错误类型时不会被校验
   - 第43轮添加了 `images_data`/`size_mb`/`media_label` 但遗漏了 `content_type`

2. **CLI search/download/interactive 命令缺少 `--content-type` 便捷参数**：
   - GUI spider 通过 `build_download_meta` 自动设置 `content_type`（如"video"/"image"/"gallery"）
   - CLI 用户只能通过 `--config '{"content_type":"gallery"}'` JSON 格式传入
   - 其他与 GUI spider 对齐的字段（cookie/referer/ua/folder-name/use-subdir/file-name）都有便捷参数
   - `content_type` 影响文件扩展名推断和图集保存路径，是高频使用字段，应提供便捷参数

3. **SKILL.md 缺少 `--content-type` CLI 参数文档**：
   - search/download/interactive 命令参数表缺少 `--content-type` 行
   - SDK 通用下载参数部分已有 `content_type` 说明，但 CLI 便捷参数部分缺失

### 修复内容

#### 修复1：`validate_config_types` 添加 `content_type` 类型校验

**文件**：`cli/defaults.py`

- `type_rules` 新增 `"content_type": str`
- 注释说明：`内容类型 video/image/gallery（DownloadWorker._infer_extension 和 _resolve_save_dir 读取）`
- 与 SDK meta 复制列表中的 `content_type` 对齐

#### 修复2：CLI search 命令添加 `--content-type` 便捷参数

**文件**：`cli/commands/search.py`

- `add_search_arguments` 新增 `--content-type` 参数
  - `type=str, default=None`
  - help 说明：`内容类型 (video/image/gallery，与 --config '{"content_type":"gallery"}' 等价，影响文件扩展名和保存路径)`
- `_build_config` 新增 `--content-type` 参数合并逻辑
  - `if getattr(args, "content_type", None): config["content_type"] = args.content_type`

#### 修复3：CLI download 命令添加 `--content-type` 便捷参数

**文件**：`cli/commands/download.py`

- `add_download_arguments` 新增 `--content-type` 参数（与 search 命令格式一致）
- `handle_download_command` 新增 `--content-type` 便捷参数合并到 `user_config`
  - `if getattr(args, "content_type", None): user_config["content_type"] = args.content_type`

#### 修复4：CLI interactive 命令添加 `--content-type` 便捷参数

**文件**：`cli/commands/interactive.py`

- `add_interactive_arguments` 新增 `--content-type` 参数（与 search/download 命令格式一致）
- `handle_interactive_command` 新增 `--content-type` 便捷参数合并到 `config`
  - `if getattr(args, "content_type", None): config["content_type"] = args.content_type`

#### 修复5：SKILL.md 文档更新

**文件**：`cli/skill/SKILL.md`

- download 命令参数表新增 `--content-type` 行
- search 命令通用参数表新增 `--content-type` 行
- interactive 命令参数表新增 `--content-type` 行
- download 命令示例新增 `--content-type gallery` 用法

### 对齐验证

| 层 | --content-type 便捷参数 | validate_config_types content_type | SKILL.md 文档 |
|---|---|---|---|
| GUI | N/A（spider 自动设置） | N/A | N/A |
| CLI search | ✅ | ✅ | ✅ |
| CLI download | ✅ | ✅ | ✅ |
| CLI interactive | ✅ | ✅ | ✅ |
| SDK | N/A（config={"content_type":"gallery"}） | ✅ | ✅ |
| REST API | N/A（config.content_type） | ✅ | ✅ |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1 只在 `validate_config_types` 中新增一条校验规则，GUI 不使用此函数
2. 修复2/3/4 只影响 CLI 命令的参数定义和处理逻辑，不影响 GUI 和 WebUI
3. 修复5 只影响文档，不影响运行时行为
4. `ApplicationController` 未修改
5. `WebController` 未修改
6. `server.py` 未修改
7. CLIRunner 未修改
8. SDK 未修改

---

## 第43轮：SDK download_video meta 复制列表补全 images_data/size_mb/media_label + validate_config_types 扩展（2026-06-07）

### 检查范围

全面对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController）在输入输出上的差异，重点关注：
1. SDK `download_video` meta 复制列表是否包含所有下载器实际读取的字段
2. `validate_config_types` 是否覆盖所有 SDK meta 复制列表中的字段
3. interactive 命令 `download_config` 提取列表是否与 SDK meta 复制列表完全对齐
4. SKILL.md 文档是否与代码一致

### 发现的差异

1. **SDK `download_video` meta 复制列表缺少 `images_data` 字段**：
   - 抖音下载器 `DouyinDownloader._download_gallery` 读取 `video_item.meta.get("images_data", [])`（第66行）
   - GUI spider 通过 `DouyinTaskBuilder.build_items` 设置 `images_data`
   - SDK `download_video` 不经过 spider，meta 复制列表不包含 `images_data`
   - 用户通过 `config={"images_data": [...]}` 传入的图集数据不会写入 `item.meta`
   - 导致 CLI/SDK/API 直接下载抖音图集时无法使用图集下载功能

2. **SDK `download_video` meta 复制列表缺少 `size_mb` 字段**：
   - 基础下载器 `BaseDownloader._download_with_strategy_fallback` 读取 `video_item.meta.get("size_mb", 0)`（第63行）
   - 用于决定是否使用分块下载策略（`ChunkedDownloader`）
   - SDK `download_video` 不经过 spider，meta 复制列表不包含 `size_mb`
   - 用户通过 `config={"size_mb": 500}` 传入的文件大小不会写入 `item.meta`
   - 导致 CLI/SDK/API 直接下载大文件时无法自动选择分块下载策略

3. **SDK `download_video` meta 复制列表缺少 `media_label` 字段**：
   - GUI spider 通过 `build_download_meta` 设置 `media_label`（如"视频"/"图集"/"实况"）
   - `ApplicationController._item_details` 日志中使用 `item.meta.get("media_label")`
   - SDK `download_video` 不经过 spider，meta 复制列表不包含 `media_label`
   - 导致 CLI/SDK/API 直接下载时日志中缺少媒体类型标签

4. **`validate_config_types` 缺少 `images_data`/`size_mb`/`media_label` 类型校验**：
   - `images_data` 应为 list
   - `size_mb` 应为 int 或 float
   - `media_label` 应为 str
   - 用户传入错误类型时不会被校验

5. **interactive 命令 `download_config` 提取列表缺少 `images_data`/`size_mb`/`media_label`**：
   - 与 SDK `download_video` meta 复制列表对齐

6. **SKILL.md 缺少 `images_data`/`size_mb`/`media_label` 的文档说明**：
   - 抖音平台参数缺少 `images_data`
   - 通用下载参数缺少 `size_mb` 和 `media_label`

### 修复内容

#### 修复1：SDK `download_video` meta 复制列表扩展

**文件**：`cli/sdk.py`

- meta 复制列表从 `("referer", "ua", "content_type", "cookie", "cookies", "proxy", "download_strategy", "folder_name", "use_subdir", "audio_url", "aweme_id", "bvid", "cid", "file_name", "preferred_filename", "is_gallery", "is_mix")` 扩展为增加 `"images_data", "size_mb", "media_label"`
- 与 GUI spider 和下载器读取的 meta 字段完全对齐

#### 修复2：`validate_config_types` 类型校验扩展

**文件**：`cli/defaults.py`

- `type_rules` 新增 `images_data: list`、`size_mb: (int, float)`、`media_label: str`
- `_TYPE_NAMES` 新增 `list: "列表"`、`float: "数字"` 映射
- 元组类型（如 `(int, float)`）的错误消息使用"或"连接各类型名称
- REST API 已委托 `validate_config_types`，自动同步

#### 修复3：interactive 命令 `download_config` 提取列表扩展

**文件**：`cli/commands/interactive.py`

- `download_config` 提取列表增加 `images_data`/`size_mb`/`media_label`
- 与 SDK `download_video` meta 复制列表完全对齐

#### 修复4：SKILL.md 文档更新

**文件**：`cli/skill/SKILL.md`

- 抖音平台参数新增 `images_data`/`size_mb`/`media_label` 说明
- 通用下载参数新增 `images_data`/`size_mb`/`media_label` 说明
- 注意事项新增 meta 字段补全记录

### 修改文件清单

| 文件 | 修改内容 |
|---|---|
| `cli/sdk.py` | `download_video` meta 复制列表新增 `images_data`/`size_mb`/`media_label` |
| `cli/defaults.py` | `validate_config_types` 新增 `images_data: list`/`size_mb: (int, float)`/`media_label: str` 校验；`_TYPE_NAMES` 新增 `list`/`float` 映射；元组类型错误消息支持 |
| `cli/commands/interactive.py` | `download_config` 提取列表新增 `images_data`/`size_mb`/`media_label` |
| `cli/skill/SKILL.md` | 抖音平台参数和通用下载参数新增 `images_data`/`size_mb`/`media_label` 说明；注意事项新增记录 |

### 对齐验证

| 层 | images_data | size_mb | media_label |
|---|---|---|---|
| GUI spider | DouyinTaskBuilder 设置 | spider 设置 | build_download_meta 设置 |
| CLI download | SDK 内部复制 ✅ | SDK 内部复制 ✅ | SDK 内部复制 ✅ |
| CLI interactive | download_config 提取 ✅ | download_config 提取 ✅ | download_config 提取 ✅ |
| SDK | meta 复制 ✅ | meta 复制 ✅ | meta 复制 ✅ |
| REST API | validate 校验 ✅ | validate 校验 ✅ | validate 校验 ✅ |
| WebSocket | validate 校验 ✅ | validate 校验 ✅ | validate 校验 ✅ |
| DouyinDownloader | 读取 images_data ✅ | N/A | N/A |
| BaseDownloader | N/A | 读取 size_mb ✅ | N/A |
| DownloadWorker | N/A | N/A | 日志 media_label ✅ |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1 只在 SDK `download_video()` 中增加 3 个字段到 meta 复制列表，GUI spider 不经过此路径（spider 自己设置这些字段）
2. 修复2 只在 `validate_config_types` 中增加 3 个字段的类型校验，GUI 不通过 config 传递这些参数
3. 修复3 只影响 CLI interactive 子命令的 `download_config` 提取列表，不影响 GUI 和 WebUI
4. 修复4 只影响 SKILL.md 文档，不影响运行时行为
5. `ApplicationController` 未修改
6. `WebController` 未修改
7. `server.py` 未修改
8. CLIRunner 未修改
9. 所有下载器未修改（只是确保 SDK 传入的 meta 字段能被下载器正确读取）

---

## 第42轮：SDK download_video trace_id 补实现 + CLI search/interactive 便捷参数补全（2026-06-07）

### 检查范围
- SDK `download_video()` 是否设置 `trace_id`（GUI spider 通过 `build_download_meta` 始终设置，第40轮记录已修复但实际未实现）
- CLI search/interactive/download 三个命令的便捷参数是否与 GUI spider `build_download_meta` 设置的字段完全对齐
- `DownloadWorker._trace_id()` 依赖 `item.meta["trace_id"]` 做日志关联

### 发现的差异

1. **SDK `download_video` 未设置 `trace_id`（第40轮修复未实际实现）**：
   - GUI spider 在 `emit_video` 时通过 `build_download_meta` 始终设置 `trace_id`
   - `DownloadWorker._trace_id()` 依赖此字段做日志关联
   - SDK `download_video` 不经过 spider，不设置 `trace_id`
   - 第40轮开发记录声称已修复，但实际代码中未实现
   - 导致 CLI/SDK 直接下载时 DownloadWorker 日志无法通过 trace_id 追踪
   - REST API/WebSocket download 的 pending_item 在 SDK 调用前设置了 trace_id（用于 WebSocket 事件），但 SDK 内部的 VideoItem 仍缺少 trace_id（用于 DownloadWorker 日志）

2. **CLI interactive 命令缺少 `--folder-name`/`--use-subdir`/`--file-name` 便捷参数**：
   - CLI download 命令已有这三个便捷参数
   - CLI interactive 命令只有 `--cookie`/`--download-strategy`/`--referer`/`--ua` 四个便捷参数
   - 用户在 interactive 模式下控制子目录结构或文件名需要手写 JSON `--config '{"folder_name":"..."}'`
   - GUI Bilibili spider 通过 `build_download_meta` 设置 `folder_name` 和 `file_name`

3. **CLI search 命令缺少 `--folder-name`/`--use-subdir`/`--file-name` 便捷参数**：
   - 同 interactive 命令，search 命令也缺少这三个便捷参数
   - 虽然搜索阶段 spider 内部会自行设置 folder_name，但用户可能需要覆盖默认值

### 修复内容

#### 修复1：SDK `download_video` 添加 `trace_id` 自动生成

**文件**：`cli/sdk.py`

- 在 meta 复制循环之前，自动生成 `trace_id` 并写入 `item.meta["trace_id"]`
- 格式与 GUI spider 对齐：`{source_prefix}-dl-{uuid8}`（如 `dy-dl-a1b2c3d4`）
- source_prefix 映射：`douyin→dy, bilibili→bili, kuaishou→ks, missav→miss`
- 与 REST API/WebSocket download 的 pending_item trace_id 格式完全一致
- 确保 DownloadWorker._trace_id() 能正确返回 trace_id，下载日志可通过 trace_id 关联

```python
# 与 GUI spider build_download_meta 对齐：设置 trace_id
import uuid as _uuid
_source_prefix = {"douyin": "dy", "bilibili": "bili", "kuaishou": "ks", "missav": "miss"}.get(source, source)
item.meta["trace_id"] = f"{_source_prefix}-dl-{_uuid.uuid4().hex[:8]}"
```

#### 修复2：CLI interactive 命令添加 `--folder-name`/`--use-subdir`/`--file-name` 便捷参数

**文件**：`cli/commands/interactive.py`

- `add_interactive_arguments` 新增三个便捷参数：
  - `--folder-name`：子目录名（与 `--config '{"folder_name":"..."}'` 等价，B站合集场景）
  - `--use-subdir`：使用子目录保存（与 `--config '{"use_subdir":true}'` 等价）
  - `--file-name`：输出文件名（与 `--config '{"file_name":"..."}'` 等价，不含扩展名）
- 便捷参数合并逻辑中新增这三个参数的合并（优先级最高，与 `--cookie`/`--referer` 等一致）
- 与 CLI download 命令的参数完全对齐

#### 修复3：CLI search 命令添加 `--folder-name`/`--use-subdir`/`--file-name` 便捷参数

**文件**：`cli/commands/search.py`

- `add_search_arguments` 新增三个便捷参数（与 interactive/download 对齐）
- `_build_config` 合并逻辑中新增这三个参数的合并（优先级最高）
- 平台别名命令（`ucrawl douyin search` 等）自动继承

### 修改文件清单

| 文件 | 修改内容 |
|---|---|
| `cli/sdk.py` | `download_video` 新增 `trace_id` 自动生成（第40轮记录但未实现的修复） |
| `cli/commands/interactive.py` | 新增 `--folder-name`/`--use-subdir`/`--file-name` 便捷参数及合并逻辑 |
| `cli/commands/search.py` | 新增 `--folder-name`/`--use-subdir`/`--file-name` 便捷参数及 `_build_config` 合并逻辑 |

### 对齐验证

| 层 | download_video trace_id | interactive 便捷参数 | search 便捷参数 |
|---|---|---|---|
| GUI | spider build_download_meta 设置 | N/A | N/A |
| CLI download | SDK 内部生成 ✅ | N/A | N/A |
| CLI interactive | SDK 内部生成 ✅ | --folder-name/--use-subdir/--file-name ✅ | N/A |
| CLI search | N/A | N/A | --folder-name/--use-subdir/--file-name ✅ |
| SDK | 自动生成 ✅ | N/A | N/A |
| REST API | pending_item + SDK 双重设置 ✅ | N/A | N/A |
| WebSocket | pending_item + SDK 双重设置 ✅ | N/A | N/A |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1 只在 SDK `download_video()` 中增加 `trace_id` 到 `item.meta`，GUI spider 不经过此路径（spider 自己设置 trace_id）
2. 修复2 只影响 CLI interactive 子命令的参数定义和合并逻辑，不影响 GUI 和 WebUI
3. 修复3 只影响 CLI search 子命令的参数定义和合并逻辑，不影响 GUI 和 WebUI
4. `ApplicationController` 未修改
5. `WebController` 未修改
6. `server.py` 未修改
7. CLIRunner 未修改

---

## 第41轮：SDK download_video meta 字段全面对齐 + ucrawl 包导出补全 + CLI --file-name 便捷参数（2026-06-07）

### 检查范围
- SDK `download_video()` meta 复制列表与 GUI spider `build_download_meta` 和 `DownloadWorker` 读取字段的差异
- `ucrawl` 包导出与 `cli` 包导出的差异
- CLI download 命令便捷参数与 GUI 控件的差异
- `validate_config_types` 类型校验覆盖范围
- interactive 命令 `download_config` 提取列表完整性
- SKILL.md 平台特定参数文档完整性

### 发现的差异

1. **SDK `download_video` meta 复制列表缺少 8 个字段**：
   - `audio_url`：B站 DASH 格式音频流 URL（BilibiliDownloader 读取）
   - `aweme_id`：抖音视频 ID（DouyinDownloader 读取）
   - `bvid`/`cid`：B站视频 BV 号和 CID（BilibiliDownloader 读取）
   - `file_name`/`preferred_filename`：文件名控制（DownloadWorker._generate_filename 读取）
   - `is_gallery`/`is_mix`：图集/合集标记（DownloadWorker 路径处理读取）
   - 这些字段在 GUI spider 的 `build_download_meta` 中设置，但 SDK `download_video` 的 meta 复制列表未包含

2. **`ucrawl` 包未导出 `GUISelection` 和 `is_selection_strategy`**：
   - `cli/__init__.py` 和 `cli/selection.py` 已导出，但 `ucrawl/__init__.py` 未透传
   - 导致 `from ucrawl import GUISelection` 失败

3. **CLI download 命令缺少 `--file-name` 便捷参数**：
   - GUI Bilibili spider 通过 `build_download_meta` 设置 `file_name`
   - CLI 用户只能通过 `--config '{"file_name":"..."}'` 传入，不够便捷

4. **`validate_config_types` 缺少 8 个字段的类型校验**：
   - `audio_url`/`aweme_id`/`bvid`/`cid`/`file_name`/`preferred_filename` 应为 str
   - `is_gallery`/`is_mix` 应为 bool

5. **interactive 命令 `download_config` 提取列表缺少 8 个字段**：
   - 与 SDK `download_video` meta 复制列表对齐

6. **SKILL.md 平台特定参数文档不完整**：
   - 缺少 `audio_url`/`aweme_id`/`bvid`/`cid`/`file_name`/`preferred_filename`/`is_gallery`/`is_mix` 的说明
   - 缺少通用下载参数（`folder_name`/`use_subdir`/`download_strategy`/`referer`/`ua`/`cookie`/`cookies`/`content_type`）的集中说明

### 修复内容

1. **SDK `download_video` meta 复制列表扩展**（`cli/sdk.py`）：
   ```python
   # 新增 8 个字段，与 GUI spider build_download_meta 和 DownloadWorker 对齐
   for key in (
       "referer", "ua", "content_type", "cookie", "cookies", "proxy",
       "download_strategy", "folder_name", "use_subdir",
       "audio_url", "aweme_id", "bvid", "cid",
       "file_name", "preferred_filename", "is_gallery", "is_mix",
   ):
   ```

2. **`ucrawl` 包导出补全**（`ucrawl/__init__.py` + `cli/__init__.py`）：
   - 新增导出 `GUISelection` 和 `is_selection_strategy`
   - 确保 `from ucrawl import GUISelection, is_selection_strategy` 可用

3. **CLI download 命令新增 `--file-name` 便捷参数**（`cli/commands/download.py`）：
   - `--file-name FILE_NAME`：输出文件名（与 `--config '{"file_name":"..."}'` 等价，不含扩展名）
   - 在 `handle_download_command` 中合并到 `user_config`

4. **`validate_config_types` 类型校验扩展**（`cli/defaults.py`）：
   - 新增 `audio_url: str`、`aweme_id: str`、`bvid: str`、`cid: str`
   - 新增 `file_name: str`、`preferred_filename: str`
   - 新增 `is_gallery: bool`、`is_mix: bool`

5. **interactive 命令 `download_config` 提取列表扩展**（`cli/commands/interactive.py`）：
   - 新增 `audio_url`/`aweme_id`/`bvid`/`cid`/`file_name`/`preferred_filename`/`is_gallery`/`is_mix`

6. **SKILL.md 文档更新**：
   - 抖音平台参数新增 `aweme_id`/`is_gallery`/`is_mix`
   - B站平台参数新增 `audio_url`/`bvid`/`cid`/`file_name`/`preferred_filename`
   - 新增"通用下载参数"小节：`folder_name`/`use_subdir`/`download_strategy`/`referer`/`ua`/`cookie`/`cookies`/`content_type`
   - 下载命令参数表新增 `--file-name`
   - 变更日志新增 meta 字段全面对齐和 ucrawl 包导出补全记录

### 验证结果
- `from ucrawl import GUISelection, is_selection_strategy` ✅
- `validate_config_types({'audio_url': '...', 'is_gallery': True, ...})` ✅
- `ucrawl download --help` 显示 `--file-name FILE_NAME` ✅
- `ucrawl search --help` 正常 ✅
- 所有 CLI/SDK/API/WebSocket 信号处理与 GUI 对齐 ✅

### 影响范围
- 仅影响 CLI/SDK/API/Skill 层，不影响 GUI 和 WebUI
- 新增字段为透传字段，不提供时行为不变
- 新增 CLI 参数为可选参数，不影响现有用法

---

## 第40轮：SDK/API trace_id 对齐 + cookie 自动加载 + meta 字段扩展 + task_started content_type 预推断（2026-06-07）

### 检查范围

全面对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController）在输入输出上的差异，重点关注：
1. SDK `download_video` 和 REST API/WebSocket `download` 是否设置 `trace_id`（GUI spider 通过 `build_download_meta` 始终设置）
2. SDK `download_video` 是否自动加载本地 cookie（GUI spider 启动时通过 AuthService 自动加载）
3. SDK `download_video` 的 meta 复制列表是否包含 `folder_name`/`use_subdir`（GUI Bilibili spider 通过 `build_download_meta` 设置）
4. REST API/WebSocket `download` 创建的 `pending_item` 是否有 `trace_id` 和预推断的 `content_type`
5. `validate_config_types` 是否覆盖 `folder_name`/`use_subdir` 字段
6. SKILL.md 文档是否与代码一致

### 发现的问题与修复

#### 修复1：SDK download_video 不设置 trace_id（下载日志无法关联）

- **文件**: `cli/sdk.py`
- **问题**: GUI spider 在 `emit_video` 时通过 `build_download_meta` 始终设置 `trace_id`，`DownloadWorker._trace_id()` 依赖此字段做日志关联。SDK `download_video` 不经过 spider，不设置 `trace_id`，导致 CLI/SDK/API 的下载日志无法通过 trace_id 追踪。
- **GUI 影响分析**: 无影响，GUI spider 始终设置 trace_id。
- **修复**: 在 SDK `download_video` 中自动生成 `trace_id`，格式与 GUI spider 对齐：`{source_prefix}-dl-{uuid8}`（如 `dy-dl-a1b2c3d4`），写入 `item.meta["trace_id"]`。

#### 修复2：REST API/WebSocket download 的 pending_item 缺少 trace_id 和 content_type

- **文件**: `app/web/server.py`
- **问题**: REST API `/api/download` 和 WebSocket `download` 消息在创建 `pending_item` 时不设置 `trace_id` 和 `content_type`，导致：
  1. `task_started` 事件中 `content_type` 始终为空字符串（因为 `pending_item.meta` 为空 dict）
  2. `DownloadWorker._trace_id()` 返回 None，日志无法关联
- **GUI 影响分析**: 无影响，GUI 通过 spider 设置这些字段。
- **修复**:
  1. 在创建 `pending_item` 后立即设置 `trace_id`（格式与 SDK 对齐）
  2. 从 URL 预推断 `content_type`（使用 `infer_content_type_from_url`），确保 `task_started` 事件包含正确的 `content_type`
  3. SDK 内部也会设置这些字段，`pending_item` 的值会被 SDK 结果覆盖（防御性兜底）

#### 修复3：SDK download_video 不自动加载本地 cookie（需要登录的平台可能下载失败）

- **文件**: `cli/defaults.py`
- **问题**: GUI spider 启动时会通过 AuthService 自动加载本地 cookie 文件（如 `dy_auth.json`、`bili_auth.json`），确保需要登录的平台能正常工作。SDK `download_video` 不经过 spider，不加载 cookie，如果用户未通过 `config` 显式传入 cookie，则下载可能因缺少认证而失败。
- **GUI 影响分析**: 无影响，GUI spider 有自己的 cookie 加载机制。
- **修复**:
  1. 在 `cli/defaults.py` 新增 `_try_load_cookie(source)` 辅助函数，尝试加载本地 cookie 文件并构建 cookie 字符串
  2. 在 `get_platform_download_defaults()` 中调用此函数，将 cookie 加入返回的默认值
  3. cookie 文件查找路径与 interactive 命令 `_find_cookie_file` 对齐（当前目录 → `~/.ucrawl/` → 项目根目录 → USER_DATA_ROOT）
  4. cookie 字符串构建与 GUI `AuthService.build_cookie_string` 对齐
  5. 用户通过 `config` 显式传入的 cookie 优先级高于自动加载的 cookie（SDK 合并逻辑保证）

#### 修复4：SDK download_video meta 复制列表缺少 folder_name/use_subdir

- **文件**: `cli/sdk.py`、`cli/commands/download.py`、`cli/commands/interactive.py`
- **问题**: GUI Bilibili spider 通过 `build_download_meta` 设置 `folder_name` 和 `use_subdir` 字段控制子目录结构。SDK `download_video` 的 meta 复制列表不包含这两个字段，即使用户通过 `config` 传入也不会写入 `item.meta`。CLI download 命令也没有 `--folder-name` 和 `--use-subdir` 便捷参数。
- **GUI 影响分析**: 无影响，GUI spider 有自己的 folder_name 设置逻辑。
- **修复**:
  1. SDK `download_video` 的 meta 复制列表扩展为 `("referer", "ua", "content_type", "cookie", "cookies", "proxy", "download_strategy", "folder_name", "use_subdir")`
  2. CLI download 命令新增 `--folder-name` 和 `--use-subdir` 便捷参数
  3. interactive 命令的 `download_config` 提取列表同步扩展
  4. `validate_config_types` 新增 `folder_name: str` 和 `use_subdir: bool` 类型校验

#### 修复5：SKILL.md 文档补充

- **文件**: `cli/skill/SKILL.md`
- **修复**:
  1. `task_started` 事件说明补充 content_type 预推断行为
  2. 注意事项新增三条：trace_id 对齐、cookie 自动加载、meta 字段扩展

### 修改文件清单

| 文件 | 修改内容 |
|---|---|
| `cli/sdk.py` | `download_video` 新增 `trace_id` 自动生成；meta 复制列表扩展 `folder_name`/`use_subdir` |
| `cli/defaults.py` | 新增 `_try_load_cookie()` 辅助函数；`get_platform_download_defaults()` 自动加载 cookie；`validate_config_types()` 新增 `folder_name`/`use_subdir` 校验 |
| `cli/commands/download.py` | 新增 `--folder-name`/`--use-subdir` 便捷参数及合并逻辑 |
| `cli/commands/interactive.py` | `download_config` 提取列表扩展 `folder_name`/`use_subdir` |
| `app/web/server.py` | REST API `/api/download` 和 WebSocket `download` 的 `pending_item` 新增 `trace_id` 和预推断 `content_type` |
| `cli/skill/SKILL.md` | `task_started` 事件说明补充；注意事项新增 trace_id/cookie/meta 三条 |

### 对齐验证

- **桌面 GUI**: 不受影响。GUI spider 有自己的 trace_id/cookie/folder_name 设置逻辑，不使用 SDK download_video
- **WebUI**: 不受影响。WebUI 的 REST API/WebSocket download 通过 SDK 调用，新增的 trace_id/content_type 只是补充了缺失的信息
- **SDK**: 增强。`download_video` 现在自动设置 trace_id 和加载 cookie，与 GUI spider 行为对齐
- **REST API**: 增强。`/api/download` 的 `task_started` 事件现在包含正确的 content_type
- **CLI download**: 增强。新增 `--folder-name`/`--use-subdir` 便捷参数
- **CLI interactive**: 增强。`download_config` 提取列表与 SDK meta 复制列表完全对齐

---

## 第39轮：CLI search/interactive/download 便捷参数全面对齐 + interactive download_config 补全（2026-06-07）

### 检查范围

全面对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController）在输入输出上的差异，重点关注：
1. CLI search/interactive/download 三个命令的便捷参数是否与 GUI spider `build_download_meta` 设置的字段对齐
2. interactive 命令的 `download_config` 提取列表是否完整
3. SKILL.md 文档是否与代码一致

### 发现的问题与修复

#### 修复1：CLI interactive download_config 缺少 cookies 和 download_strategy

- **文件**: `cli/commands/interactive.py`
- **问题**: interactive 命令从搜索 config 中提取下载相关配置时，只提取了 `("proxy", "referer", "ua", "content_type", "cookie")`，缺少 `cookies`（dict 格式）和 `download_strategy`。而 SDK `download_video` 的 meta 复制列表已包含这两个字段，GUI spider 也通过 `build_download_meta` 设置 `download_strategy`。当用户通过 `--config '{"cookies": {"key": "val"}, "download_strategy": "m3u8"}'` 传入时，这些字段不会被传递给 `sdk.download_video()`。
- **GUI 影响分析**: 无影响，GUI 不使用 interactive 命令路径。
- **修复**: 提取列表扩展为 `("proxy", "referer", "ua", "content_type", "cookie", "cookies", "download_strategy")`，与 SDK meta 复制列表完全对齐。

#### 修复2：CLI download 命令缺少 --referer 和 --ua 便捷参数

- **文件**: `cli/commands/download.py`
- **问题**: CLI download 命令已有 `--cookie` 和 `--download-strategy` 便捷参数，但缺少 `--referer` 和 `--ua` 便捷参数。GUI spider 通过 `build_download_meta` 设置 referer 和 ua，CLI 用户需要手写 JSON `--config '{"referer":"...", "ua":"..."}'` 才能覆盖，不如 GUI 直观。
- **GUI 影响分析**: 无影响，GUI 不使用 CLI download 命令。
- **修复**:
  1. 新增 `--referer` 参数：`ucrawl download "标题" --url "..." --source bilibili --referer "https://www.bilibili.com"`
  2. 新增 `--ua` 参数：`ucrawl download "标题" --url "..." --source douyin --ua "Mozilla/5.0 ..."`
  3. 两个便捷参数自动合并到 config 中，与 `--config` 等价但更直观

#### 修复3：CLI search 命令缺少 --cookie/--referer/--ua/--download-strategy 便捷参数

- **文件**: `cli/commands/search.py`
- **问题**: CLI search 命令只支持 `--config '{"cookie":"..."}'` 传入 cookie/referer/ua/download_strategy，不如 CLI download 命令直观。虽然 search 命令的 config 会传递给 spider，spider 会自动设置 ua/referer，但用户可能需要覆盖这些默认值（例如自定义 UA 或传入认证 Cookie）。
- **GUI 影响分析**: 无影响，GUI 不使用 CLI search 命令。
- **修复**:
  1. 新增 `--cookie`、`--download-strategy`、`--referer`、`--ua` 四个便捷参数
  2. 在 `_build_config` 中合并这些便捷参数（优先级与独立参数一致，高于 `--config` JSON）
  3. 平台别名命令（`ucrawl douyin search` 等）自动继承，因为它们复用 `add_search_arguments`

#### 修复4：CLI interactive 命令缺少 --cookie/--referer/--ua/--download-strategy 便捷参数

- **文件**: `cli/commands/interactive.py`
- **问题**: 与 search 命令同样缺少便捷参数，用户需要手写 JSON。
- **GUI 影响分析**: 无影响，GUI 不使用 CLI interactive 命令。
- **修复**:
  1. 新增 `--cookie`、`--download-strategy`、`--referer`、`--ua` 四个便捷参数
  2. 在 config 合并逻辑中添加便捷参数合并（在 `--config` JSON 合并之后）

#### 修复5：SKILL.md 文档未记录新增便捷参数

- **文件**: `cli/skill/SKILL.md`
- **问题**: SKILL.md 的参数参考表和 CLI 示例中未记录 `--cookie`、`--referer`、`--ua`、`--download-strategy` 便捷参数。
- **修复**:
  1. 通用参数表新增 `--cookie`、`--download-strategy`、`--referer`、`--ua` 四行
  2. 下载命令参数表新增 `--cookie`、`--download-strategy`、`--referer`、`--ua` 四行
  3. 交互式命令参数表新增 `--cookie`、`--download-strategy`、`--referer`、`--ua` 四行
  4. CLI 示例新增 search/download 使用便捷参数的示例

### 修改文件清单

| 文件 | 修改内容 |
|---|---|
| `cli/commands/interactive.py` | `download_config` 提取列表增加 `cookies`/`download_strategy`；新增 `--cookie`/`--download-strategy`/`--referer`/`--ua` 便捷参数及合并逻辑 |
| `cli/commands/download.py` | 新增 `--referer`/`--ua` 便捷参数及合并逻辑 |
| `cli/commands/search.py` | 新增 `--cookie`/`--download-strategy`/`--referer`/`--ua` 便捷参数及 `_build_config` 合并逻辑 |
| `cli/skill/SKILL.md` | 参数参考表和 CLI 示例新增便捷参数文档 |

### 对齐验证

- **桌面 GUI**: 不受影响。GUI 通过 spider 设置 meta 字段，不使用 CLI 命令
- **WebUI**: 不受影响。WebUI 的 REST API/WebSocket 不使用 CLI 便捷参数，直接通过 config JSON 传入
- **SDK**: 不受影响。SDK 已正确支持所有 config 字段，便捷参数只是 CLI 层面的语法糖
- **REST API**: 不受影响。REST API 已通过 `config` JSON 对象支持所有字段
- **CLI 三命令对齐**: search/download/interactive 三个命令现在都有 `--cookie`/`--download-strategy`/`--referer`/`--ua` 便捷参数，与 GUI spider `build_download_meta` 设置的字段完全对齐

---

## 第38轮：SDK download_video 平台默认 ua/referer/content_type 对齐 + CLI 便捷参数（2026-06-07）

### 检查范围

全面对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController）在 `download_video` 直接下载场景下的输入输出差异，重点关注：
1. GUI spider 通过 `build_download_meta` 设置的平台特定 meta 字段（ua、referer、download_strategy、content_type），SDK `download_video` 是否对齐
2. CLI download 命令是否提供与 GUI 等价的便捷参数
3. `validate_config_types` 是否覆盖所有下载相关配置字段

### 发现的问题与修复

#### 修复1：SDK download_video 不设置平台默认 ua/referer（下载可能因缺少请求头失败）

- **文件**: `cli/defaults.py`（新增 `get_platform_download_defaults`）、`cli/sdk.py`
- **问题**: GUI spider 在 `emit_video` 时通过 `build_download_meta` 设置平台特定的 `ua`（User-Agent）和 `referer`（来源页），例如：
  - BilibiliDownloader 需要 `Referer: https://www.bilibili.com` 才能正常下载音视频流
  - DouyinDownloader 需要 `Referer: https://www.douyin.com/`
  - KuaishouDownloader 需要 `Referer: https://www.kuaishou.com/`
  - MissAVDownloader 需要 `Referer: https://missav.ai/`
  SDK `download_video` 不经过 spider，只从用户 config 中读取 ua/referer，如果用户未提供则 meta 中没有这些字段。虽然各下载器有 fallback 默认值（从 cfg 读取），但 SDK 应主动设置这些默认值，与 GUI spider 行为对齐。
- **修复**:
  1. 在 `cli/defaults.py` 新增 `get_platform_download_defaults(source)` 函数，返回每个平台的默认 ua/referer
  2. 在 SDK `download_video` 中调用此函数，将平台默认值合并到 config（用户 config 优先级更高）
  3. 平台默认值来源与各下载器的 fallback 值完全一致（从 cfg 读取，兜底 DEFAULT_USER_AGENT）

#### 修复2：SDK download_video 下载前不推断 content_type（文件扩展名可能错误）

- **文件**: `cli/defaults.py`（新增 `infer_content_type_from_url`）、`cli/sdk.py`
- **问题**: GUI spider 在创建 VideoItem 时就设置 `content_type`（如 "video"/"gallery"/"image"），`DownloadWorker._infer_extension` 使用 `content_type` 来推断文件扩展名。SDK `download_video` 只在下载后从文件扩展名推断 `content_type`，下载前未设置。如果下载的是图片，`_infer_extension` 会默认返回 ".mp4"，虽然下载后 `_detect_actual_file_type` 会修正扩展名，但初始 `local_path` 会有错误的扩展名。
- **修复**:
  1. 在 `cli/defaults.py` 新增 `infer_content_type_from_url(url)` 函数，从 URL 路径推断 content_type
  2. 在 SDK `download_video` 中，如果用户未提供 `content_type`，则从 URL 推断并设置到 meta
  3. 推断逻辑：URL 含视频扩展名→"video"，含图片扩展名→"image"，无法推断→空字符串（下载后再推断）

#### 修复3：SDK download_video meta 复制列表缺少 download_strategy

- **文件**: `cli/sdk.py`
- **问题**: GUI spider 通过 `build_download_meta` 设置 `download_strategy`（如快手 spider 设置 "m3u8" 或 "http"），`DownloadWorker._log_details` 读取此字段用于日志。SDK `download_video` 的 meta 复制列表不包含 `download_strategy`，即使用户通过 config 传入也不会写入 item.meta。
- **修复**: 将 meta 复制列表从 `("referer", "ua", "content_type", "cookie", "cookies", "proxy")` 扩展为 `("referer", "ua", "content_type", "cookie", "cookies", "proxy", "download_strategy")`

#### 修复4：validate_config_types 缺少 download_strategy/referer/ua 类型校验

- **文件**: `cli/defaults.py`
- **问题**: `validate_config_types` 的 `type_rules` 不包含 `download_strategy`、`referer`、`ua` 字段，用户传入错误类型时不会被校验。
- **修复**: 在 `type_rules` 中新增 `"download_strategy": str`、`"referer": str`、`"ua": str`

#### 修复5：CLI download 命令缺少 --cookie 和 --download-strategy 便捷参数

- **文件**: `cli/commands/download.py`
- **问题**: CLI download 命令只支持 `--config '{"cookie": "..."}'` 传入 cookie，不如 GUI 直接输入方便。同样，`download_strategy` 也需要手写 JSON。
- **修复**:
  1. 新增 `--cookie` 参数：`ucrawl download "标题" --url "..." --source douyin --cookie "sessionid=xxx"`
  2. 新增 `--download-strategy` 参数：`ucrawl download "标题" --url "..." --source kuaishou --download-strategy m3u8`
  3. 两个便捷参数自动合并到 config 中，与 `--config` 等价但更直观

### 修改文件清单

| 文件 | 修改内容 |
|---|---|
| `cli/defaults.py` | 新增 `infer_content_type_from_url()`、`get_platform_download_defaults()` 函数；`validate_config_types` 新增 `download_strategy`/`referer`/`ua` 类型校验 |
| `cli/sdk.py` | `download_video` 新增平台默认 ua/referer 设置、URL content_type 推断、download_strategy meta 复制；导入新增函数 |
| `cli/commands/download.py` | 新增 `--cookie` 和 `--download-strategy` 便捷参数 |

### 对齐验证

- **桌面 GUI**: 不受影响。GUI 通过 spider 设置 meta 字段，不使用 SDK `download_video`
- **WebUI**: 不受影响。WebUI 的 `/api/download` 和 WebSocket `download` 使用 SDK `download_video`，新增的 meta 字段（ua/referer/content_type/download_strategy）是下载器已支持的字段，属于补齐而非变更
- **下载器**: 各下载器已有 fallback 默认值，SDK 主动设置平台默认值只是确保与 GUI spider 行为一致，不改变下载器逻辑
- **REST API**: `validate_config_types` 新增字段校验与 REST API 共用，三层校验逻辑一致

---

## 第37轮：下载器 proxy 全链路传递 + SDK cookies/cookie config 校验对齐（2026-06-07）

### 检查范围

全面对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController）在输入输出上的差异，重点关注下载器层面对 `video_item.meta["proxy"]` 的使用情况，以及 SDK `download_video` 的 meta 复制列表是否与 GUI 下载器实际读取的字段一致。

### 发现的问题与修复

#### 修复1：N_m3u8DL-RE 外部工具不支持 proxy 参数（MissAV 下载链路断裂）

- **文件**: `app/core/downloaders/external.py`
- **问题**: `NM3U8DLREExternalTool.build_download_command` 不接受 `proxy` 参数，构造的命令行中不包含 `--proxy` 选项。当 MissAV spider 在 `video_item.meta["proxy"]` 中设置代理后，N_m3u8DL-RE 下载器无法将代理传递给外部工具，导致 MissAV 视频下载走直连而非代理，在需要翻墙的环境下下载失败。
- **GUI 影响分析**: GUI 的 MissAV spider 同样在 `video_item.meta` 中设置了 `proxy`，但下载器一直未读取。此修复使 GUI 和 CLI/SDK/API 同时受益——对 GUI 而言是 bug 修复（之前 proxy 仅用于 Playwright 浏览，下载阶段未走代理），不会破坏原有行为。
- **修复**:
  1. `build_download_command` 增加 `proxy: str | None = None` 参数
  2. 当 `proxy` 非空时，追加 `--proxy <proxy>` 到命令行
  3. `m3u8.py` 中调用时传入 `proxy=video_item.meta.get("proxy")`

#### 修复2：FFmpeg 外部工具不支持 proxy 参数

- **文件**: `app/core/downloaders/external.py`、`app/core/downloaders/ffmpeg.py`
- **问题**: `FFmpegExternalTool.build_download_command` 不接受 `proxy` 参数，且 `FFmpegDownloader.download` 中的 `requests.head` 也不传递代理。FFmpeg 支持 `-http_proxy` 参数，但未被使用。
- **GUI 影响分析**: 同修复1，GUI 中 FFmpegDownloader 也不读取 proxy，此修复对 GUI 同样是 bug 修复。
- **修复**:
  1. `build_download_command` 增加 `proxy: str | None = None` 参数
  2. 当 `proxy` 非空时，追加 `-http_proxy <proxy>` 到命令行
  3. `ffmpeg.py` 中 `requests.head` 传入 `proxies`，`build_download_command` 传入 `proxy=proxy`

#### 修复3：HTTP 基础下载器 `_download_http_file` 不支持 proxy

- **文件**: `app/core/downloaders/base.py`
- **问题**: `_download_http_file` 方法不接受 `proxy` 参数，`requests.get` 调用中不传递 `proxies`。抖音/快手等平台通过 `_download_with_strategy_fallback` 调用此方法时，即使 `video_item.meta` 中有 proxy，也不会被使用。
- **GUI 影响分析**: GUI 中抖音/快手 spider 不在 `video_item.meta` 中设置 proxy（它们通过 Playwright 浏览器上下文使用代理），因此此修复不影响 GUI 原有行为。仅当 CLI/SDK/API 用户显式传入 `config={"proxy": "..."}` 时才会生效。
- **修复**:
  1. `_download_http_file` 增加 `proxy: str | None = None` 参数
  2. 当 `proxy` 非空时，构造 `proxies = {"http": proxy, "https": proxy}` 传给 `requests.get`
  3. `_download_with_strategy_fallback` 调用时传入 `proxy=video_item.meta.get("proxy")`

#### 修复4：ChunkedDownloader 不支持 proxy

- **文件**: `app/core/downloaders/chunked.py`
- **问题**: `ChunkedDownloader.download` 中的 `requests.head` 和 `download_chunk` 内的 `requests.get` 都不传递代理。
- **GUI 影响分析**: 同修复3，GUI 中不通过 `video_item.meta` 传递 proxy，不影响原有行为。
- **修复**:
  1. 从 `video_item.meta` 读取 `proxy`，构造 `proxies`
  2. `requests.head` 和 `requests.get` 均传入 `proxies`

#### 修复5：BilibiliDownloader 不支持 proxy

- **文件**: `app/core/downloaders/bilibili.py`
- **问题**: `download_stream` 内的 `requests.get` 不传递代理。
- **GUI 影响分析**: 同修复3，不影响 GUI 原有行为。
- **修复**: 从 `video_item.meta` 读取 `proxy`，构造 `proxies`，传给 `requests.get`

#### 修复6：SDK `download_video` meta 复制列表缺少 `cookies`

- **文件**: `cli/sdk.py`
- **问题**: SDK `download_video` 方法将用户 config 中的字段复制到 `item.meta` 时，只复制了 `("referer", "ua", "content_type", "cookie", "proxy")`，缺少 `cookies`（dict 格式）。而下载器（抖音、B站）会优先读取 `cookies`（dict），导致用户通过 `config={"cookies": {"key": "value"}}` 传入的 cookies 不会被下载器看到。
- **GUI 影响分析**: GUI spider 在内部设置 `cookies`（dict），不通过 config 传入，因此不影响 GUI。
- **修复**: 复制列表增加 `"cookies"`，变为 `("referer", "ua", "content_type", "cookie", "cookies", "proxy")`

#### 修复7：config 类型校验缺少 `cookies`/`cookie` 字段

- **文件**: `cli/defaults.py`
- **问题**: `validate_config_types` 的 `type_rules` 只包含 `max_items`/`max_pages`/`timeout`/`individual_only`/`priority`/`proxy`，缺少 `cookies`（dict）和 `cookie`（str）。用户传入错误类型的 `cookies` 或 `cookie` 时不会被校验，可能导致下载器静默失败。
- **GUI 影响分析**: 无影响，GUI 不通过 config 传递这些参数。
- **修复**:
  1. `type_rules` 增加 `"cookies": dict` 和 `"cookie": str`
  2. `_TYPE_NAMES` 增加 `dict: "字典"` 映射
  3. REST API 已委托 `validate_config_types`，自动同步

### 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `app/core/downloaders/external.py` | N_m3u8DL-RE 和 FFmpeg 的 `build_download_command` 增加 `proxy` 参数 |
| `app/core/downloaders/m3u8.py` | 传递 `proxy=video_item.meta.get("proxy")` 给 N_m3u8DL-RE |
| `app/core/downloaders/ffmpeg.py` | `requests.head` 和 `build_download_command` 传递 proxy |
| `app/core/downloaders/base.py` | `_download_http_file` 增加 `proxy` 参数，`_download_with_strategy_fallback` 传递 proxy |
| `app/core/downloaders/chunked.py` | `requests.head` 和 `requests.get` 传递 proxies |
| `app/core/downloaders/bilibili.py` | `requests.get` 传递 proxies |
| `cli/sdk.py` | meta 复制列表增加 `"cookies"` |
| `cli/defaults.py` | `type_rules` 增加 `cookies`/`cookie`，`_TYPE_NAMES` 增加 `dict` |

### 验证要点

1. MissAV 通过 CLI/SDK/API 下载时，`config={"proxy": "http://..."}` 的代理现在会传递到 N_m3u8DL-RE 命令行
2. 抖音/快手/B站通过 CLI/SDK/API 下载时，`config={"proxy": "http://..."}` 的代理会传递到 `requests.get`
3. SDK `download_video(config={"cookies": {"key": "val"}})` 的 cookies 会正确复制到 `item.meta`，下载器可读取
4. 错误类型的 `cookies`/`cookie` 会被校验拒绝（如 `cookies: "string"` 会报错"必须是字典"）
5. GUI 原有行为不受影响（GUI spider 不通过 `item.meta["proxy"]` 传递代理给下载器，GUI 下载抖音/快手/B站时不设置 proxy）

---

## 第36轮：CLI/API/SDK/Skill 下载器 cookie/proxy 对齐 + interactive 默认选择策略修正（2026-06-07）

### 检查范围

对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController）在下载器层面的输入输出差异，以及 CLI interactive 命令的默认选择策略合理性。

### 发现的问题与修复

#### 修复1：抖音下载器缺少 cookie 支持（与快手下载器不对齐）

- **文件**: `app/core/downloaders/douyin.py`
- **问题**: 快手下载器（第30-35行）已支持从 `video_item.meta` 读取 cookie（支持 dict 格式的 `cookies` 和 string 格式的 `cookie`），但抖音下载器只构建了 `User-Agent` 和 `Referer` 头，不读取 cookie。当 CLI/SDK/REST API 通过 `config={"cookie": "..."}` 传入 cookie 时，抖音下载器不会将其加入请求头，导致需要认证的视频下载失败。
- **GUI 影响分析**: GUI 流程中，抖音 spider 通过自身 HTTP session 管理 cookie，不依赖 `item.meta["cookie"]`，因此此修复不影响 GUI。
- **修复**: 在 headers 构建后添加与快手下载器一致的 cookie 读取逻辑：
  ```python
  cookie_dict = video_item.meta.get("cookies")
  if isinstance(cookie_dict, dict):
      headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
  elif isinstance(video_item.meta.get("cookie"), str):
      headers["Cookie"] = video_item.meta["cookie"]
  ```
- **影响**: CLI/SDK/REST API 直接下载抖音视频时，cookie 现在能正确传递到下载请求。

#### 修复2：B站下载器缺少 cookie 支持（与快手下载器不对齐）

- **文件**: `app/core/downloaders/bilibili.py`
- **问题**: 同修复1，B站下载器也不读取 cookie。对于需要 SESSDATA 认证的大会员视频，CLI/SDK/REST API 传入的 cookie 不会被使用。
- **GUI 影响分析**: GUI 流程中，B站 spider 通过自身 HTTP session 管理 cookie，不依赖 `item.meta["cookie"]`，因此此修复不影响 GUI。
- **修复**: 同修复1，添加与快手下载器一致的 cookie 读取逻辑。
- **影响**: CLI/SDK/REST API 直接下载B站视频时，cookie 现在能正确传递到下载请求。

#### 修复3：SDK `download_video` proxy 未写入 `item.meta`（仅 missav 写入，其他平台丢失）

- **文件**: `cli/sdk.py` 第424-433行
- **问题**: SDK `download_video()` 中，MissAV 的 proxy 转换后单独写入 `item.meta["proxy"]`，但后续的 `for key in ("referer", "ua", "content_type", "cookie")` 循环不包含 `"proxy"`。这导致：
  1. MissAV 的 proxy 写了两次（先单独写，再被循环覆盖一次，结果相同但逻辑冗余）
  2. 其他平台的 proxy 完全丢失（如用户通过 `config={"proxy": "http://..."}` 传入代理，不会写入 `item.meta`）
- **修复**:
  1. 将 MissAV proxy 转换后的 `item.meta["proxy"] = merged["proxy"]` 移除（由后续循环统一写入）
  2. 将循环中的 key 列表从 `("referer", "ua", "content_type", "cookie")` 扩展为 `("referer", "ua", "content_type", "cookie", "proxy")`
  3. 更新注释说明 proxy 的用途
- **影响**: 所有平台的 proxy 现在都能正确写入 `item.meta`，为下载器未来支持代理读取做好准备。MissAV 行为不变（proxy 转换后由循环写入，效果相同）。

#### 修复4：CLI interactive 默认选择策略不合理（GUISelection 在纯 CLI 环境弹窗）

- **文件**: `cli/commands/interactive.py` 第440-442行
- **问题**: CLI interactive 命令在用户未指定选择策略时，默认使用 `GUISelection()`。`GUISelection` 会尝试弹出 PyQt6 对话框，在纯 CLI 环境（无 display）下降级为 `RuleSelection(all_items=True)` 全选。但 interactive 命令本身就是终端交互模式，用户已在终端操作，弹窗体验不一致。应默认使用 `InteractiveTTYSelection()`，让用户在终端中选择。
- **GUI 影响分析**: 此修改仅影响 CLI interactive 命令，不影响 GUI（GUI 使用 `ApplicationController` 的 `SelectionDialog`）。
- **修复**:
  1. 将默认选择策略从 `GUISelection()` 改为 `InteractiveTTYSelection()`
  2. 移除不再使用的 `GUISelection` 导入
  3. 更新注释说明选择原因
- **影响**: CLI interactive 命令在二次选择时，默认在终端交互选择，不再弹窗。

### 已验证的对齐项（无需修改）

以下项目经检查已正确对齐，无需修改：

1. **快手下载器 cookie 支持** — 已在第35轮修复，支持 dict 和 string 两种格式
2. **MissAV 下载器 proxy 支持** — 通过 N_m3u8DL_RE_Downloader 读取 `item.meta["proxy"]`
3. **SDK `search()` config 合并** — 三层合并顺序一致，MissAV proxy 转换正确
4. **SDK `download_video()` config 合并** — 与 `search()` 完全一致
5. **CLI search 命令 `_build_selection_strategy`** — 默认 `RuleSelection(all_items=True)` 合理
6. **REST API `/api/download`** — 委托给 SDK `download_video()`，由 SDK 内部合并配置
7. **WebSocket `download`** — 同 REST API，委托给 SDK
8. **SKILL.md** — 文档与代码行为一致
9. **四层返回值格式** — 完全一致
10. **四层错误处理** — 一致

### 未修改的文件（确认不影响 GUI 和 WebUI）

- `app/controllers/application_controller.py` — 未修改
- `app/web/controller.py` — 未修改
- `app/web/static/` — 未修改
- `app/models/video_item.py` — 未修改

## 第35轮：interactive 命令代码实际修复 + SDK cookie 传递 + 快手下载器 cookie 兼容（2026-06-07）

### 检查范围
重新检查 CLI / SDK / REST API / Skill 四层与成熟 GUI 输入输出的差异。发现第33/34轮记录的修复内容**未实际应用到代码**（文档已写但代码未改），本轮完成实际代码修改。

### 发现的差异

| # | 差异 | GUI 行为 | CLI/SDK/API 实际行为 | 影响 |
|---|---|---|---|---|
| 1 | **CLI interactive `add_interactive_arguments` 参数不完整** | N/A | 只有 `--save-dir`/`--no-download`/`--pretty` 3个参数，缺少 `--run-timeout`/`--quiet`/`--config`/`--all`/`--first`/`--last`/`--select`/`--exclude`/`--pipe`/`--preload-choices` | 用户无法通过 interactive 命令使用这些参数，与 search 命令不对齐 |
| 2 | **CLI interactive `sdk.search()` 调用 BUG：`config=config`** | SDK `search()` 接受 `**config` 解包 | 代码使用 `config=config`，将整个 dict 作为单个 `config` 关键字参数传入，导致 spider 收到嵌套 dict 而非展开的参数 | 平台特定参数（max_items/proxy/cookie 等）无法传递给 spider |
| 3 | **CLI interactive `sdk.search()` 冗余传 `max_items=max_items`** | max_items 已包含在 config dict 中 | 代码额外传 `max_items=max_items`，与 `**config` 展开重复 | 重复参数，且 max_items 已通过 config 传入 |
| 4 | **CLI interactive `sdk.download_video()` 未传 `timeout`/`config`/`verbose`** | GUI 通过 CLIRunner 有超时机制 | 代码只传 `url`/`source`/`title`/`save_dir`，缺少 `timeout`/`config`/`verbose` | 用户设置了 `--run-timeout` 但下载超时不受控；cookie/proxy 不传给下载器；下载进度不显示 |
| 5 | **CLI interactive 下载结果未检查** | GUI 通过信号处理下载成功/失败 | 代码丢弃 `sdk.download_video()` 返回值，不检查下载是否成功 | 下载失败时无任何错误提示 |
| 6 | **CLI interactive 不区分超时和其他错误** | GUI/CLIRunner 区分超时和其他错误 | 代码统一输出"下载失败" | 用户无法区分是超时还是其他原因 |
| 7 | **CLI interactive `--no-download` + `--pretty` 无输出** | search 命令在 `--no-download` + `--pretty` 时输出 JSON | interactive 在 `--no-download` 时不输出 JSON 格式结果 | 用户无法获取结构化搜索结果 |
| 8 | **SDK `download_video` 未将 `cookie` 复制到 `item.meta`** | GUI spider 通过 `item.meta` 传递 cookie 到 DownloadWorker | SDK 只复制 `referer`/`ua`/`content_type` 到 `item.meta`，遗漏 `cookie` | CLI/API/SDK 直接下载时 cookie 不传给下载器 |
| 9 | **快手下载器只读 `cookies`（dict），不兼容 `cookie`（string）** | GUI spider 传入 `cookies`（dict 格式） | CLI/SDK 传入 `cookie`（string 格式），快手下载器只读 `video_item.meta.get("cookies")` | CLI/SDK 下载快手视频时 cookie 不生效 |

### 修复内容

#### 修复1：CLI interactive `add_interactive_arguments` 补全参数

**文件**：`cli/commands/interactive.py`

- 补全 `--run-timeout`（整体超时秒数）
- 补全 `--quiet`/`-q`（不输出 spider 日志）
- 补全 `--config`（平台特定配置 JSON 字符串）
- 补全二次选择参数组：`--all`/`--first`/`--last`/`--select`/`--exclude`/`--pipe`/`--preload-choices`
- 与 search 命令参数完全对齐

#### 修复2：CLI interactive `sdk.search()` 调用修正

**文件**：`cli/commands/interactive.py`

- `config=config` → `**config`：修复 BUG，将 config dict 展开为关键字参数
- 移除冗余的 `max_items=max_items`：max_items 已通过 `**config` 传入
- 新增 `selection=selection` 参数：支持二次选择策略
- 新增 `run_timeout=run_timeout` 参数：支持整体超时

#### 修复3：CLI interactive `sdk.download_video()` 全面补全

**文件**：`cli/commands/interactive.py`

- 新增 `timeout=download_timeout`：使用 `run_timeout or 300` 作为下载超时
- 新增 `config=download_config`：从搜索 config 中提取 `proxy`/`referer`/`ua`/`content_type`/`cookie`
- 新增 `verbose=verbose`：根据 `--quiet` 参数控制下载进度输出
- 新增下载结果检查：检查 `dl_result.get("status")`，区分 `ok`/`timeout`/`error`
- 新增超时区分：`dl_status == "timeout"` 或 `"超时" in error_msg` 时输出"下载超时"
- 新增 `error_count` 计数：全部失败时返回退出码 1
- 新增 `TypeError`/`ValueError` 异常捕获：与 REST API `/api/download` 对齐

#### 修复4：CLI interactive `--no-download` + `--pretty` 输出

**文件**：`cli/commands/interactive.py`

- 在 `--no-download` + `--pretty` 时输出 JSON 格式的搜索结果
- 与 search 命令 `_print_pretty` 行为对齐

#### 修复5：SDK `download_video` 增加 `cookie` 到 `item.meta` 复制列表

**文件**：`cli/sdk.py`

- `item.meta` 复制列表从 `("referer", "ua", "content_type")` 扩展为 `("referer", "ua", "content_type", "cookie")`
- 与 GUI spider meta 对齐：cookie 需要传给 DownloadWorker

#### 修复6：快手下载器 cookie 格式兼容

**文件**：`app/core/downloaders/kuaishou.py`

- 新增 `elif isinstance(video_item.meta.get("cookie"), str)` 分支
- GUI spider 传入 `cookies`（dict 格式），CLI/SDK 传入 `cookie`（string 格式）
- 两种格式都能正确设置 `headers["Cookie"]`

### 新增逻辑：interactive 命令二次选择策略构建

**文件**：`cli/commands/interactive.py`

- `--pipe` → `PipeSelection()`
- `--preload-choices` → `PipeSelection(preloaded_choices=rounds)`
- 默认 → `RuleSelection(select=..., exclude=..., all_items=..., first=..., last=...)`
- 与 search 命令 `_build_selection_strategy` 对齐

### 新增逻辑：interactive 命令 `--config` 合并与校验

**文件**：`cli/commands/interactive.py`

- 合并 `--config` JSON 到 config dict（过滤 None 值）
- 校验 JSON 格式（必须是 JSON 对象）
- 校验已知参数类型（调用 `validate_config_types`）
- 与 search 命令 `_build_config` 对齐

### 对齐验证

| 层 | interactive 参数 | search config 展开 | download timeout | download cookie | pretty+no-download |
|---|---|---|---|---|---|
| GUI | N/A | spider 内部 | CLIRunner | spider meta | N/A |
| CLI interactive | ✅ 全部补全 | ✅ **config | ✅ timeout | ✅ cookie in config+meta | ✅ JSON 输出 |
| CLI search | ✅ 已有 | ✅ **config | N/A | N/A | ✅ 已有 |
| CLI download | N/A | N/A | ✅ 已有 | N/A | ✅ 已有 |
| SDK | N/A | ✅ 已有 | ✅ 已有 | ✅ cookie in meta | N/A |
| REST API | N/A | ✅ 已有 | ✅ 已有 | ✅ 已有 | N/A |
| 快手下载器 | N/A | N/A | N/A | ✅ cookie+cookies 兼容 | N/A |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1-4 只影响 CLI interactive 子命令，不影响 GUI 和 WebUI
2. 修复5 只在 SDK `download_video()` 中增加 `cookie` 到 `item.meta` 复制列表，GUI spider 不经过此路径（spider 自己设置 item.meta）
3. 修复6 只在快手下载器中增加 `cookie`（string）兼容分支，不影响 GUI spider 传入 `cookies`（dict）的路径
4. `ApplicationController` 未修改
5. `WebController` 未修改
6. `server.py` 未修改
7. CLIRunner 未修改
8. 其他下载器（douyin/bilibili/missav/m3u8/ffmpeg/chunked/external）未修改

---

## 第34轮：interactive 命令下载参数补全 + entry 参数对齐 + Skill 示例导入修正（2026-06-07）

### 检查范围
重新检查 CLI / SDK / REST API / WebSocket / Skill 五层与成熟 GUI 输入输出的差异。重点对比 interactive 命令的下载参数传递、entry 入口参数完整性、Skill 示例导入路径一致性。

### 发现的差异

| # | 差异 | GUI 行为 | CLI/SDK/API 行为 | 影响 |
|---|---|---|---|---|
| 1 | **CLI interactive `sdk.download_video()` 未传 `timeout` 参数** | CLIRunner 有 `_wait_downloads(timeout=300)` 超时机制 | interactive 的 `sdk.download_video()` 未传 `timeout`，使用 SDK 默认值 300 但用户无法通过 `--run-timeout` 自定义 | 用户设置了 `--run-timeout` 但下载超时不受其控制 |
| 2 | **CLI interactive `download_config` 遗漏 `cookie`** | GUI spider 通过 `item.meta` 传递 cookie 到 DownloadWorker | interactive 的 `download_config` 只提取 `proxy/referer/ua/content_type`，遗漏了 `cookie` | 抖音/B站/快手下载时 cookie 不传给下载器，可能因缺少登录态而失败 |
| 3 | **entry/interactive_entry.py 参数不完整** | N/A | `entry/interactive_entry.py` 只定义了 `--save-dir`、`--no-download`、`--pretty` 三个参数，缺少 `--run-timeout`、`--quiet`、`--config`、`--all`、`--first`、`--last`、`--select`、`--exclude`、`--pipe`、`--preload-choices` | 通过 `ucrawl-i` 命令调用时这些参数不可用，与 `ucrawl interactive` 行为不一致 |
| 4 | **Skill 示例导入路径与 SKILL.md 推荐不一致** | N/A | SKILL.md 推荐 `from ucrawl import UcrawlSDK`，但三个示例使用 `from cli import UcrawlSDK` | 用户按 SKILL.md 文档写代码时可能困惑导入路径不一致 |
| 5 | **test_cli_sdk.py 测试断言 `s.select` 是方法而非属性** | N/A | `RuleSelection.select` 是方法（`def select(self, items, prompt)`），规则存储在 `_select_rule` 属性中，但测试断言 `s.select == "0,2"` 会比较方法对象而非字符串 | 2 个测试始终失败 |

### 其他层检查结果

经全面检查，以下层已与 GUI 完全对齐，无需修改：
- **CLI search 命令**：参数完整，`_build_config`/`_build_selection_strategy`/`handle_search_command` 逻辑正确
- **CLI download 命令**：参数完整，`--config`/`--quiet`/`--pretty`/`--timeout` 全部支持
- **CLI scan 命令**：`--quiet`/`--pretty`/`--limit` 全部支持
- **CLI platforms 命令**：`--quiet`/`--pretty`/`--describe` 全部支持
- **SDK `search()`**：`selection`/`run_timeout`/`**config` 参数正确处理
- **SDK `download_video()`**：`config`/`progress_callback`/`timeout` 参数正确处理，timeout 状态不被 on_error 覆盖
- **REST API `/api/search`**：`run_timeout`/`selection`/`config`/`download` 参数完整
- **REST API `/api/download`**：`config`/`timeout`/`progress_callback` 参数完整，pending_item 属性同步
- **WebSocket download**：参数校验完整，事件广播与 GUI 对齐
- **WebController**：`task_started`/`task_finished`/`task_error` 事件字段完整
- **CLIRunner**：超时处理、状态更新、debug_logger 与 GUI 对齐
- **REST API/WebSocket download 异常路径**：TypeError/ValueError 和 Exception 路径正确处理，无需区分超时（这些是参数校验异常，不是下载超时）
- **WebController `_on_task_error`**：始终设置 `"❌ 失败"`，与 GUI `_on_download_error` 对齐（WebController 的 dl_manager 没有超时机制，超时只在 SDK `download_video()` 和 CLIRunner 中有）

### 修复内容

#### 修复1：CLI interactive `download_config` 增加 `cookie`

**文件**：`cli/commands/interactive.py`

- `download_config` 的 key 列表从 `("proxy", "referer", "ua", "content_type")` 扩展为 `("proxy", "referer", "ua", "content_type", "cookie")`
- 与 GUI spider meta 对齐：cookie/proxy/referer/ua/content_type 都需要传给下载
- 抖音/B站/快手下载时 cookie 会被传给 DownloadWorker，确保登录态可用

#### 修复2：CLI interactive `sdk.download_video()` 传入 `timeout` 参数

**文件**：`cli/commands/interactive.py`

- 新增 `download_timeout = run_timeout or 300` 变量
- 将 `timeout=download_timeout` 传入 `sdk.download_video()`
- 与 CLI download 命令对齐：用户可通过 `--run-timeout` 自定义下载超时
- 默认 300s 与 SDK `download_video()` 的默认值一致

#### 修复3：entry/interactive_entry.py 参数对齐

**文件**：`entry/interactive_entry.py`

- 将手动定义的 3 个参数替换为 `add_interactive_arguments(parser)` 调用
- 与 `cli/commands/interactive.py` 的参数定义完全对齐
- 通过 `ucrawl-i` 命令调用时，`--run-timeout`/`--quiet`/`--config`/二次选择参数全部可用
- 移除不再需要的 `from cli.main import _ensure_search_defaults` 导入

#### 修复4：Skill 示例导入路径修正

**文件**：`cli/skill/examples/01_basic_search.py`、`02_collection_download.py`、`03_batch_search.py`

- 将 `from cli import UcrawlSDK` 改为 `from ucrawl import UcrawlSDK`
- 将 `from cli import UcrawlSDK, PipeSelection` 改为 `from ucrawl import UcrawlSDK, PipeSelection`
- 将 `from cli import UcrawlSDK, RuleSelection` 改为 `from ucrawl import UcrawlSDK, RuleSelection`
- 与 SKILL.md 推荐的导入路径一致

#### 修复5：test_cli_sdk.py 测试断言修正

**文件**：`tests/test_cli_sdk.py`

- `test_str_indices`：`s.select` → `s._select_rule`（RuleSelection.select 是方法，规则存储在 _select_rule 属性中）
- `test_dict_strategy_rule`：`s.select` → `s._select_rule`（同上）

### 对齐验证

| 层 | interactive download timeout | interactive download cookie | entry 参数 | Skill 导入 |
|---|---|---|---|---|
| GUI | CLIRunner _wait_downloads | spider meta → item | N/A | N/A |
| CLI interactive | ✅ timeout=download_timeout | ✅ cookie in download_config | N/A | N/A |
| CLI download | ✅ timeout=args.timeout | N/A（直接下载无 cookie） | N/A | N/A |
| entry interactive | N/A | N/A | ✅ add_interactive_arguments | N/A |
| Skill examples | N/A | N/A | N/A | ✅ from ucrawl import |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1/2 只影响 CLI interactive 子命令的下载参数传递，不影响 GUI 和 WebUI
2. 修复3 只影响 `ucrawl-i` 命令的参数定义，不影响 GUI 和 WebUI
3. 修复4 只影响 Skill 示例的导入路径，不影响运行时行为
4. 修复5 只影响测试断言，不影响运行时行为
5. `ApplicationController` 未修改
6. `WebController` 未修改
7. `server.py` 未修改
8. CLIRunner 未修改
9. SDK 未修改

---

## 第33轮：interactive 命令实际代码修复 + download_video 返回值检查（2026-06-07）

### 检查范围
重新检查 CLI / SDK / REST API / WebSocket / Skill 五层与成熟 GUI 输入输出的差异。发现第32轮记录的修复内容**未实际应用到代码**（文档已写但代码未改），本轮完成实际代码修改，并发现额外问题。

### 发现的差异

| # | 差异 | GUI 行为 | CLI/SDK/API 行为 | 影响 |
|---|---|---|---|---|
| 1 | **第32轮修复1未实现：CLI interactive 命令缺少参数** | N/A | `add_interactive_arguments` 仍只有 `--save-dir`、`--no-download`、`--pretty`，缺少 `--run-timeout`、`--quiet`、`--config`、`--all`、`--first`、`--last`、`--select`、`--exclude`、`--pipe`、`--preload-choices` | SKILL.md 文档描述的功能无法通过 CLI 使用 |
| 2 | **第32轮修复2未实现：CLI interactive `sdk.search()` 有 `config=config` BUG** | N/A | `sdk.search(source=..., keyword=..., max_items=max_items, save_dir=..., download=..., config=config)` 传 `config=config` 导致 `**config` 捕获为 `{"config": config_dict}` | 交互式搜索配置合并逻辑错误 |
| 3 | **新发现：CLI interactive `sdk.download_video()` 返回值未检查** | GUI 通过信号更新状态 | `sdk.download_video()` 返回 dict 但返回值被丢弃，下载失败但不返回 "error" 时用户看不到错误 | 下载静默失败，用户无感知 |
| 4 | **新发现：CLI interactive `sdk.download_video()` 未传 `config`** | GUI 通过 spider meta 传递 | 下载调用未传 `config` 参数，missav 代理等平台特定配置不会用于下载 | missav 下载不使用代理，可能失败 |
| 5 | **新发现：CLI interactive `--pretty` 参数未用于结果输出** | N/A | `--no-download` + `--pretty` 时不输出 JSON 结果 | 用户无法获取结构化搜索结果 |
| 6 | **新发现：CLI interactive 不区分下载超时和其他错误** | GUI 区分 "❌ 超时" 和 "❌ 失败" | `except Exception` 统一输出 "下载失败"，不区分超时 | 用户无法区分超时和真正的错误 |

### 其他层检查结果

经全面检查，以下层已与 GUI 完全对齐，无需修改：
- **CLI search 命令**：参数完整，`_build_config`/`_build_selection_strategy`/`handle_search_command` 逻辑正确
- **CLI download 命令**：参数完整，`--config`/`--quiet`/`--pretty`/`--timeout` 全部支持
- **CLI scan 命令**：`--quiet`/`--pretty`/`--limit` 全部支持
- **CLI platforms 命令**：`--quiet`/`--pretty`/`--describe` 全部支持
- **SDK `search()`**：`selection`/`run_timeout`/`**config` 参数正确处理
- **SDK `download_video()`**：`config`/`progress_callback`/`timeout` 参数正确处理，timeout 状态不被 on_error 覆盖
- **REST API `/api/search`**：`run_timeout`/`selection`/`config`/`download` 参数完整
- **REST API `/api/download`**：`config`/`timeout`/`progress_callback` 参数完整，pending_item 属性同步
- **WebSocket download**：参数校验完整，事件广播与 GUI 对齐
- **WebController**：`task_started`/`task_finished`/`task_error` 事件字段完整
- **CLIRunner**：超时处理、状态更新、debug_logger 与 GUI 对齐

### 修复内容

#### 修复1：CLI interactive 命令补全 SKILL.md 文档中声明的参数（实际代码实现）

**文件**：`cli/commands/interactive.py`

- `add_interactive_arguments` 新增以下参数（与 search 命令对齐）：
  - `--run-timeout`：整体超时秒数
  - `--quiet` / `-q`：不输出 spider 日志
  - `--config`：平台特定配置 JSON 字符串
  - `--all`：全选
  - `--first`：只选第一个
  - `--last`：只选最后一个
  - `--select`：指定选中索引
  - `--exclude`：指定排除索引
  - `--pipe`：强制 stdin 管道选择
  - `--preload-choices`：预加载多次选择
- 新增 `_build_selection_strategy()` 函数（与 search 命令对齐）
- `handle_interactive_command` 修改：
  - 使用 `--quiet` 控制 SDK verbose 参数
  - 合并 `--config` JSON 到平台默认配置（含类型校验和 `validate_config_types`）
  - 构建 selection 策略并传给 `sdk.search()`
  - 传递 `run_timeout` 给 `sdk.search()`
  - 确认执行时显示超时设置
  - 校验 `--config` JSON 格式和类型
  - 校验 `--run-timeout > 0`

#### 修复2：CLI interactive `sdk.search()` 调用修正（实际代码实现）

**文件**：`cli/commands/interactive.py`

- 将 `sdk.search(source=..., keyword=..., max_items=max_items, save_dir=..., download=..., config=config)` 修正为 `sdk.search(source=..., keyword=..., save_dir=..., download=..., selection=selection, run_timeout=run_timeout, **config)`
- 修复 `config=config` BUG：改为 `**config` 解包
- 移除冗余的 `max_items=max_items` 参数

#### 修复3：CLI interactive `sdk.download_video()` 返回值检查 + 传 config + 区分超时

**文件**：`cli/commands/interactive.py`

- 捕获 `sdk.download_video()` 返回值 `dl_result`
- 检查 `dl_result.get("status") != "ok"` 时输出错误信息
- 区分超时（`status == "timeout"` 或错误信息含 "超时"）和其他错误
- 传入 `config=download_config`（从搜索 config 中提取 proxy/referer/ua/content_type）
- 统计下载错误数，全部失败时返回退出码 1

#### 修复4：CLI interactive `--pretty` 参数用于结果输出

**文件**：`cli/commands/interactive.py`

- `--no-download` + `--pretty` 时输出 JSON 格式的搜索结果
- 与 search 命令 `--no-download` + `--pretty` 行为对齐

### 对齐验证

| 层 | interactive 参数 | sdk.search() 调用 | download_video 返回值检查 | download_video config |
|---|---|---|---|---|
| GUI | N/A | N/A | 信号驱动 | spider meta |
| CLI search | 全部参数 ✅ | CLIRunner 直接调用 | N/A | N/A |
| CLI interactive | 全部参数 ✅ | **config 解包 ✅ | 检查 ✅ | 传入 ✅ |
| SDK | N/A | N/A | 返回 dict | 支持 config 参数 |
| REST API | N/A | N/A | 检查 ✅ | 传入 ✅ |
| WebSocket | N/A | N/A | 检查 ✅ | 传入 ✅ |

### 不影响桌面 GUI 和 WebUI 的保证

1. 所有修改仅涉及 `cli/commands/interactive.py`，不影响 GUI 和 WebUI
2. `ApplicationController` 未修改
3. `WebController` 未修改
4. `server.py` 未修改
5. CLIRunner 未修改
6. SDK 未修改
7. 其他 CLI 命令（search/download/scan/platforms）未修改

---

## 第32轮：interactive 命令参数对齐与 SDK timeout 状态覆盖 BUG 修复（2026-06-07）

### 检查范围
全面检查 CLI / SDK / REST API / WebSocket / Skill 五层与成熟 GUI（桌面 ApplicationController）输入输出的差异，重点对比 CLI interactive 命令参数完整性、SDK download_video 超时状态正确性。

### 发现的差异

| # | 差异 | GUI 行为 | CLI/SDK/API 行为 | 影响 |
|---|---|---|---|---|
| 1 | **CLI interactive 命令缺少 SKILL.md 文档中声明的参数** | N/A | `add_interactive_arguments` 只定义了 `--save-dir`、`--no-download`、`--pretty`，缺少 `--run-timeout`、`--quiet`、`--config`、`--all`、`--first`、`--last`、`--select`、`--exclude`、`--pipe`、`--preload-choices` | SKILL.md 文档描述的功能无法通过 CLI 使用，用户无法在交互式模式中指定超时、静默模式、配置、选择策略等 |
| 2 | **CLI interactive `sdk.search()` 调用有 `config=config` BUG** | N/A | `sdk.search()` 使用 `**config` 接收平台参数，传 `config=config` 会导致 `**config` 捕获为 `{"config": config_dict}`，产生嵌套 dict | 交互式搜索的配置合并逻辑错误，平台参数可能不生效 |
| 3 | **SDK `download_video` 的 `on_error` 回调可能覆盖 timeout 状态** | GUI 无超时机制 | `dl_manager.stop_all()` 在 finally 块中执行，可能触发 `on_error` 回调，将 `result_holder["status"]` 从 "timeout" 覆盖为 "error" | 超时下载返回 "error" 而非 "timeout"，调用方无法区分超时与其他错误 |

### 修复内容

#### 修复1：CLI interactive 命令补全 SKILL.md 文档中声明的参数

**文件**：`cli/commands/interactive.py`

- `add_interactive_arguments` 新增以下参数（与 search 命令对齐）：
  - `--run-timeout`：整体超时秒数（与 search --run-timeout 对齐）
  - `--quiet` / `-q`：不输出 spider 日志（与 search --quiet 对齐）
  - `--config`：平台特定配置 JSON 字符串（与 search/download --config 对齐）
  - `--all`：全选（与 search --all 对齐）
  - `--first`：只选第一个（与 search --first 对齐）
  - `--last`：只选最后一个（与 search --last 对齐）
  - `--select`：指定选中索引（与 search --select 对齐）
  - `--exclude`：指定排除索引（与 search --exclude 对齐）
  - `--pipe`：强制 stdin 管道选择（与 search --pipe 对齐）
  - `--preload-choices`：预加载多次选择（与 search --preload-choices 对齐）
- 新增 `_build_selection_strategy()` 函数（与 search 命令 `_build_selection_strategy` 对齐）
- `handle_interactive_command` 修改：
  - 使用 `--quiet` 控制 SDK verbose 参数
  - 合并 `--config` JSON 到平台默认配置（含类型校验）
  - 构建 selection 策略并传给 `sdk.search()`
  - 传递 `run_timeout` 给 `sdk.search()`
  - 确认执行时显示超时设置

#### 修复2：CLI interactive `sdk.search()` 调用修正

**文件**：`cli/commands/interactive.py`

- 将 `sdk.search(source=..., keyword=..., max_items=max_items, save_dir=..., download=..., config=config)` 修正为 `sdk.search(source=..., keyword=..., save_dir=..., download=..., selection=selection, run_timeout=run_timeout, **config)`
- 修复 `config=config` BUG：`sdk.search()` 使用 `**config` 接收平台参数，传 `config=config` 会导致嵌套 dict，改为 `**config` 解包
- 移除冗余的 `max_items=max_items` 参数（已在 config dict 中，通过 `**config` 解包传递）

#### 修复3：SDK `download_video` 的 `on_error` 回调防止覆盖 timeout 状态

**文件**：`cli/sdk.py`

- `on_error` 回调中：`result_holder["status"] = "error"` → `if result_holder["status"] != "timeout": result_holder["status"] = "error"`
- 原因：`dl_manager.stop_all()` 在 finally 块中执行，可能触发 `on_error` 回调，此时 `result_holder["status"]` 可能已被超时检测设为 "timeout"
- 修复后：超时检测设置的 "timeout" 状态不会被 `on_error` 回调覆盖，确保调用方能正确区分超时与其他错误
- 向后兼容：非超时场景行为不变（`on_error` 仍设置 "error"）

### 对齐验证

| 层 | interactive 参数 | sdk.search() 调用 | download_video timeout 状态 |
|---|---|---|---|
| GUI | N/A | N/A | N/A（无超时机制） |
| CLI search | 全部参数 ✅ | CLIRunner 直接调用 | N/A |
| CLI interactive | 全部参数 ✅（与 search 对齐） | **config 解包 ✅ | N/A |
| SDK | N/A | N/A | timeout 不被 on_error 覆盖 ✅ |
| REST API | N/A | N/A | N/A（使用 SDK） |
| WebSocket | N/A | N/A | N/A（使用 SDK） |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1 只影响 CLI interactive 子命令的参数定义和处理逻辑，不影响 GUI 和 WebUI
2. 修复2 只影响 CLI interactive 子命令的 `sdk.search()` 调用方式，不影响 GUI 和 WebUI
3. 修复3 只影响 SDK `download_video` 的 `on_error` 回调内部逻辑，GUI 不使用 SDK
4. `ApplicationController` 未修改
5. `WebController` 未修改
6. `server.py` 未修改
7. CLIRunner 未修改

---

## 第31轮：下载超时状态区分与错误路径 pending_item 属性同步（2026-06-07）

### 检查范围
全面检查 CLI / SDK / REST API / WebSocket / Skill 五层与成熟 GUI（桌面 ApplicationController）输入输出的差异，重点对比下载超时状态区分、错误路径 pending_item 属性同步、scan 错误响应字段一致性。

### 发现的差异

| # | 差异 | GUI 行为 | CLI/SDK/API 行为 | 影响 |
|---|---|---|---|---|
| 1 | **SDK `download_video` 超时返回 "error" 而非 "timeout"** | CLIRunner.run() 超时返回 `{"status": "timeout"}` | SDK `download_video` 超时返回 `{"status": "error"}`，调用方无法区分超时与其他错误 | CLI/REST API/WebSocket 无法向用户展示"超时"而非"失败" |
| 2 | **REST API/WebSocket download 不区分 "❌ 超时" 和 "❌ 失败"** | CLIRunner `_wait_downloads` 将超时 item 标记为 `"❌ 超时"` | REST API/WebSocket download 的 SDK result error 路径一律使用 `"❌ 失败"` | WebSocket 客户端无法区分超时与其他错误 |
| 3 | **REST API/WebSocket download 错误时未从 SDK 结果更新 pending_item** | GUI 直接读取 VideoItem（DownloadManager 已更新 local_path/title/meta） | REST API/WebSocket download 的 SDK result error 路径只设置 status/progress/download_error，不更新 local_path/title/meta | 错误事件广播的 local_path/title/meta 可能过时 |
| 4 | **WebController `_apply_video_state` 不处理 "❌ 超时" 状态** | GUI 不区分超时（无超时机制） | WebController `_apply_video_state` 只在 `"✅ 完成"/"❌ 失败"` 时包含 local_path/content_type，`"❌ 超时"` 不包含 | 通过 WebController start_crawl 触发的超时事件缺少 local_path/content_type |
| 5 | **CLI download `_print_pretty` 不区分超时** | N/A | `_print_pretty` 一律显示 `"❌ 下载失败"`，即使 SDK 返回 `"timeout"` | CLI 用户无法从 --pretty 输出区分超时 |
| 6 | **SDK/REST API scan 错误响应缺少 `directory` 字段** | N/A | 成功响应包含 `directory`，错误响应不包含 | 字段不一致 |

### 修复内容

#### 修复1：SDK `download_video` 超时返回 "timeout" 状态

**文件**：`cli/sdk.py`

- 超时检测路径：`result_holder["status"] = "error"` → `result_holder["status"] = "timeout"`
- 错误返回路径：`"status": "error"` → `"status": result_holder["status"]`（动态取值，超时为 "timeout"，其他为 "error"）
- 与 CLIRunner.run() 对齐：超时返回 `"timeout"`，让调用方可区分超时与其他错误
- 向后兼容：现有调用方检查 `result.get("status") == "ok"` 判断成功，非 "ok" 均为失败，不受影响

#### 修复2：REST API `/api/download` 区分 "❌ 超时" 和 "❌ 失败"

**文件**：`app/web/server.py`

- SDK result error 路径：检查 `result.get("status") == "timeout" or "超时" in error_msg`
  - 超时：`pending_item.status = "❌ 超时"`
  - 其他：`pending_item.status = "❌ 失败"`
- `video_state_changed` 事件：`"status": "❌ 失败"` → `"status": pending_item.status`（动态取值）
- 与 GUI/CLI CLIRunner 对齐：超时标记为 "❌ 超时"

#### 修复3：WebSocket `download` 区分 "❌ 超时" 和 "❌ 失败"

**文件**：`app/web/server.py`

- 同修复2，WebSocket download 的 SDK result error 路径也区分超时和失败
- `video_state_changed` 事件也使用 `pending_item.status` 动态取值

#### 修复4：REST API/WebSocket download 错误时从 SDK 结果更新 pending_item

**文件**：`app/web/server.py`

- SDK result error 路径新增：
  - `if result.get("local_path"): pending_item.local_path = result["local_path"]`
  - `if result.get("title"): pending_item.title = result["title"]`
  - `if result.get("meta") and isinstance(result["meta"], dict): pending_item.meta.update(result["meta"])`
- 与成功路径对齐：成功时也更新 local_path/title/meta
- 确保错误事件广播的 local_path/title/meta 是最新值

#### 修复5：WebController `_apply_video_state` 增加 "❌ 超时" 状态支持

**文件**：`app/web/controller.py`

- `if status in ("✅ 完成", "❌ 失败"):` → `if status in ("✅ 完成", "❌ 失败", "❌ 超时"):`
- 超时状态时也包含 `local_path` 和 `content_type`，与失败状态行为一致
- 向后兼容：新增状态值，现有客户端忽略未知状态

#### 修复6：CLI download `_print_pretty` 区分超时

**文件**：`cli/commands/download.py`

- 检查 `result.get("status") == "timeout" or "超时" in result.get("error", "")`
  - 超时：显示 `"❌ 下载超时: ..."`
  - 其他：显示 `"❌ 下载失败: ..."`
- 与 search 命令的 `_print_pretty` 对齐（search 已正确显示不同状态）

#### 修复7：SDK/REST API scan 错误响应增补 `directory` 字段

**文件**：`cli/sdk.py`、`app/web/server.py`

- SDK `scan_directory` 错误响应：`{"status": "error", "error": str(e)}` → `{"status": "error", "error": str(e), "directory": directory}`
- REST API `/api/scan` 错误响应：同上
- 与成功响应字段对齐（成功响应包含 `directory`）

#### 修复8：SKILL.md 文档更新

**文件**：`cli/skill/SKILL.md`

- download 返回结构 `status` 字段：`"ok" 或 "error"` → `"ok"（成功）、"error"（下载失败）、"timeout"（下载超时）`
- 异常处理说明增补：SDK 返回 `{"status": "timeout"}` 时 `pending_item` 状态为 `"❌ 超时"`，`video_state_changed` 事件 `status` 也为 `"❌ 超时"`

### 对齐验证

| 层 | 下载超时 status | 下载超时 item.status | 错误时更新 pending_item | scan 错误含 directory |
|---|---|---|---|---|
| GUI | N/A（无超时机制） | N/A | 直接读取 VideoItem | N/A |
| CLI | timeout | ❌ 超时 | N/A（无 pending_item） | N/A |
| SDK | timeout | ❌ 超时 | N/A（返回 dict） | ✅ |
| REST API | timeout | ❌ 超时 | ✅（local_path/title/meta） | ✅ |
| WebSocket | timeout | ❌ 超时 | ✅（local_path/title/meta） | N/A |
| WebController | N/A | ❌ 超时（_apply_video_state） | 直接读取 VideoItem | N/A |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1 只影响 SDK `download_video` 的返回值 status 字段，GUI 不使用 SDK
2. 修复2/3/4 只影响 REST API/WebSocket download 的 SDK result error 路径，GUI 不经过此路径
3. 修复5 是 WebController 的防御性增强，GUI 的 `_apply_video_state` 不受影响（GUI 无超时机制，不会传入 "❌ 超时" 状态）
4. 修复6 只影响 CLI download 的 `--pretty` 输出格式
5. 修复7 只影响 SDK/REST API scan 的错误响应字段
6. `ApplicationController` 未修改
7. CLIRunner 的超时检测逻辑未修改（已正确标记 "❌ 超时"）

---

## 第30轮：事件字段完整性对齐与 interactive 命令 BUG 修复（2026-06-07）

### 检查范围
全面检查 CLI / SDK / REST API / WebSocket / Skill 五层与成熟 GUI（桌面 ApplicationController）输入输出的差异，重点对比 WebSocket 事件字段完整性和 interactive 子命令的正确性。

### 发现的差异

| # | 差异 | GUI 行为 | CLI/SDK/API 行为 | 影响 |
|---|---|---|---|---|
| 1 | **[BUG] interactive.py `sdk.download_video(video_id=vid)` 参数名错误** | SDK 签名是 `download_video(url, source, ...)` | interactive.py 传 `video_id=vid`，会抛 `TypeError: got an unexpected keyword argument 'video_id'` | interactive 子命令下载功能完全不可用 |
| 2 | **[死代码] server.py `_add_download_to_controller` 函数从未被调用** | N/A | 该函数定义了 30+ 行代码但从未被任何路径调用，REST API/WebSocket download 直接创建 pending_item | 代码维护困惑 |
| 3 | **`task_error` 事件缺少 `local_path`/`content_type`/`title`** | GUI 直接读取 VideoItem 对象获取完整信息 | `task_error` 事件只有 `video_id` 和 `error`，与 `task_finished`（含 local_path/content_type/title）不一致 | WebSocket 客户端无法从单个事件获取完整错误信息 |
| 4 | **`task_started` 事件缺少 `title`/`content_type`** | GUI 直接读取 VideoItem 对象获取完整信息 | `task_started` 事件只有 `video_id` 和 `local_path`，与 `task_finished`（含 content_type/title）不一致 | WebSocket 客户端在下载开始时无法显示完整信息 |
| 5 | **SDK `download_video` 不将 `content_type` 从 merged config 写入 `item.meta`** | GUI spider 设置 `item.meta["content_type"]` | SDK 只复制 `referer`/`ua` 到 item.meta，不复制 `content_type` | 用户传 `config={"content_type": "gallery"}` 时 DownloadWorker 无法使用正确的文件扩展名 |
| 6 | **REST API `/api/download` 错误响应 `local_path` 硬编码为 `""`** | GUI 直接读取 `item.local_path` | 错误响应的 `local_path` 和 `content_type` 始终为 `""`，但 `video_state_changed` 事件使用 `pending_item.local_path or ""` | HTTP 错误响应与 WebSocket 事件不一致 |

### 修复内容

#### 修复1：interactive.py `sdk.download_video` 参数名修正

**文件**：`cli/commands/interactive.py`

- 将 `video_id=vid` 改为 `url=item_url`，与 SDK `download_video(url, source, ...)` 签名对齐
- 从 item dict 中读取 `url`（视频原始地址）而非 `id`（内部 UUID），下载需要 url
- 传入 `title=item_title` 和 `source=platform_id`，与 CLI download 命令和 REST API `/api/download` 对齐
- 传入 `save_dir=save_dir`，与 CLI download 命令对齐

#### 修复2：删除 server.py 死代码 `_add_download_to_controller`

**文件**：`app/web/server.py`

- 删除 `_add_download_to_controller` 函数（约 30 行），该函数从未被任何路径调用
- REST API/WebSocket download 已直接创建 `pending_item` 并添加到 `controller.videos`，不需要此辅助函数

#### 修复3：WebController `task_error` 事件增补 `local_path`/`content_type`/`title`

**文件**：`app/web/controller.py`

- `_on_task_error` 方法的 `task_error` 事件从 `{"video_id", "error"}` 扩展为 `{"video_id", "error", "local_path", "content_type", "title"}`
- 与 `task_finished` 事件字段对齐，让 WebSocket 客户端无需额外请求即可获取完整错误信息
- 向后兼容：新增字段，现有客户端忽略未知字段

#### 修复4：WebController `task_started` 事件增补 `title`/`content_type`

**文件**：`app/web/controller.py`

- `_on_task_started` 方法的 `task_started` 事件从 `{"video_id", "local_path"}` 扩展为 `{"video_id", "local_path", "title", "content_type"}`
- 与 `task_finished` 事件字段对齐，让 WebSocket 客户端在下载开始时即可显示完整信息
- 向后兼容：新增字段，现有客户端忽略未知字段

#### 修复5：REST API/WebSocket download `task_error`/`task_started` 事件增补

**文件**：`app/web/server.py`

- REST API `/api/download` 的 `task_started` 事件增补 `title`/`content_type`
- REST API `/api/download` 的 3 个 `task_error` 路径（TypeError/ValueError、Exception、result error）增补 `local_path`/`content_type`/`title`
- WebSocket `download` 的 `task_started` 事件增补 `title`/`content_type`
- WebSocket `download` 的 3 个 `task_error` 路径增补 `local_path`/`content_type`/`title`
- 与 WebController 事件格式完全对齐

#### 修复6：REST API `/api/download` 错误响应 `local_path`/`content_type` 使用 pending_item 实际值

**文件**：`app/web/server.py`

- TypeError/ValueError 和 Exception 错误路径的 HTTP 响应：
  - `local_path` 从硬编码 `""` 改为 `pending_item.local_path or ""`
  - `content_type` 从硬编码 `""` 改为 `pending_item.meta.get("content_type", "") if pending_item.meta else ""`
- 与 `video_state_changed` 事件使用相同的值，确保一致性

#### 修复7：SDK `download_video` 增补 `content_type` 到 `item.meta`

**文件**：`cli/sdk.py`

- 将 `content_type` 加入复制到 `item.meta` 的 key 列表：`("referer", "ua")` → `("referer", "ua", "content_type")`
- 与 GUI spider 行为对齐：spider 设置 `item.meta["content_type"]`，DownloadWorker 使用它推断文件扩展名
- 用户传 `config={"content_type": "gallery"}` 时，DownloadWorker 可正确使用 `.jpeg` 扩展名

#### 修复8：SKILL.md 文档更新

**文件**：`cli/skill/SKILL.md`

- `task_started` 事件字段更新为 `video_id, local_path, title, content_type`
- `task_error` 事件字段更新为 `video_id, error, local_path, content_type, title`
- 注意事项新增 `task_started` 和 `task_error` 事件增强说明

### 对齐验证

| 层 | task_started 字段 | task_error 字段 | 错误响应 local_path |
|---|---|---|---|
| GUI | 直接读取 VideoItem | 直接读取 VideoItem | N/A |
| CLI | N/A（无 WebSocket） | N/A（无 WebSocket） | N/A |
| SDK | N/A（返回 dict） | N/A（返回 dict） | N/A |
| REST API | video_id + local_path + title + content_type | video_id + error + local_path + content_type + title | pending_item.local_path or "" |
| WebSocket | video_id + local_path + title + content_type | video_id + error + local_path + content_type + title | N/A |
| WebController | video_id + local_path + title + content_type | video_id + error + local_path + content_type + title | N/A |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1 只影响 interactive 子命令（CLI 交互式引导），不影响 GUI 和 WebUI
2. 修复2 是删除死代码，不影响任何运行时行为
3. 修复3/4/5 是向后兼容的事件字段增强（新增字段，现有客户端忽略未知字段）
4. 修复6 只影响 REST API HTTP 错误响应，不影响 GUI（GUI 不使用 REST API）
5. 修复7 只影响 SDK `download_video` 的 meta 写入，不影响 GUI（GUI 通过 spider 设置 content_type）
6. WebController 的事件增强不影响桌面 GUI（GUI 直接读取 VideoItem 对象，不依赖 WebSocket 事件）
7. CLIRunner 不受影响（无 WebSocket 客户端，只更新内存状态）
8. `ApplicationController` 未修改

---

## 第29轮：下载事件流与失败事件字段对齐（2026-06-07）

### 检查范围
全面检查 CLI / SDK / REST API / WebSocket / Skill 五层与成熟 GUI（桌面 ApplicationController）输入输出的差异，重点对比下载流程的事件状态转换顺序和失败事件字段完整性。

### 发现的差异

| # | 差异 | GUI 行为 | CLI/SDK/API 行为 | 影响 |
|---|---|---|---|---|
| 1 | REST API/WebSocket download 跳过"⏳ 等待中"状态 | GUI 流程：item_found("⏳ 等待中") → task_started("⏳ 下载中...") → task_progress → task_finished | REST API/WebSocket download 直接创建 pending_item 为"⏳ 下载中..."，跳过"⏳ 等待中" | WebUI 前端无法看到"⏳ 等待中" → "⏳ 下载中..."的完整状态转换 |
| 2 | download 失败时 video_state_changed 缺少 local_path 和 content_type | WebController _apply_video_state 在"❌ 失败"状态时包含 local_path 和 content_type | REST API/WebSocket download 的6个失败路径（TypeError/ValueError、Exception、result error）只广播 video_id/status/progress | WebSocket 客户端无法在失败时更新本地缓存的 local_path 和 content_type |
| 3 | SDK `__init__` config 类型校验顺序错误 | 期望：config 非 dict 时抛出 TypeError | `dict(config or {})` 在类型校验之前执行，字符串被当作可迭代对象导致 ValueError | SDK 用户传入 config="not a dict" 时收到 ValueError 而非 TypeError |

### 修复内容

#### 修复1：REST API `/api/download` pending_item 初始状态对齐 GUI 事件流

**文件**：`app/web/server.py`

- 创建 `pending_item` 时使用 `status="⏳ 等待中"`（与 GUI `_on_spider_item_found` 对齐）
- 先广播 `item_found`（状态为"⏳ 等待中"）
- 再切换到 `status="⏳ 下载中..."` 并广播 `task_started` + `video_state_changed`
- 事件流变为：item_found("⏳ 等待中") → task_started("⏳ 下载中...") → task_progress → task_finished/task_error
- 与 GUI 完整事件流对齐

#### 修复2：WebSocket `download` pending_item 初始状态对齐 GUI 事件流

**文件**：`app/web/server.py`

- 同修复1，WebSocket `download` 消息处理器也使用相同的事件流
- 创建 `pending_item` 时使用 `status="⏳ 等待中"`
- 先广播 `item_found`，再切换到 `"⏳ 下载中..."` 并广播 `task_started` + `video_state_changed`

#### 修复3：REST API/WebSocket download 失败时 video_state_changed 增补 local_path 和 content_type

**文件**：`app/web/server.py`

- REST API `/api/download` 的3个失败路径（TypeError/ValueError、Exception、result error）：
  - `video_state_changed` 事件增加 `local_path` 和 `content_type` 字段
  - 与 WebController `_apply_video_state` 在"❌ 失败"状态时的行为对齐
- WebSocket `download` 的3个失败路径（同上）：
  - 同样增补 `local_path` 和 `content_type`
- 向后兼容：新增字段，现有客户端忽略未知字段

#### 修复4：SDK `__init__` config 类型校验顺序修正

**文件**：`cli/sdk.py`

- 将 `if config is not None and not isinstance(config, dict): raise TypeError(...)` 移到 `self.default_config = dict(config or {})` 之前
- 确保字符串等非 dict 类型在 `dict()` 转换之前被拦截，抛出正确的 TypeError
- 与 `search()` 和 `download_video()` 的 config 校验行为对齐

### 对齐验证

| 层 | 下载事件流 | 失败 video_state_changed 字段 |
|---|---|---|
| GUI | item_found("⏳ 等待中") → task_started("⏳ 下载中...") → task_progress → task_finished | 直接读取 VideoItem（含 local_path/content_type） |
| CLI | 内存状态更新（无 WebSocket 广播） | N/A |
| SDK | progress_callback 回调 | N/A（返回 dict） |
| REST API | item_found("⏳ 等待中") → task_started("⏳ 下载中...") → task_progress → task_finished | video_id + status + progress + local_path + content_type |
| WebSocket | item_found("⏳ 等待中") → task_started("⏳ 下载中...") → task_progress → task_finished | video_id + status + progress + local_path + content_type |
| WebController | item_found("⏳ 等待中") → task_started("⏳ 下载中...") → task_progress → task_finished | video_id + status + progress + local_path + content_type |

### 不影响桌面 GUI 和 WebUI 的保证

1. 修复1/2 只改变 REST API/WebSocket download 的事件广播顺序，不影响 GUI（GUI 使用 DownloadManager 信号，不经过 REST API/WebSocket）
2. 修复3 是向后兼容的字段增强（新增字段，现有客户端忽略未知字段）
3. WebController `_apply_video_state` 不受影响（它已经包含 local_path 和 content_type）
4. 修复4 只影响 SDK `__init__` 的校验顺序，不影响 GUI 和 WebUI（它们不直接使用 SDK 构造函数）
5. CLIRunner 不受影响（无 WebSocket 客户端，只更新内存状态）

---

## 第28轮：SDK progress_callback 与 WebSocket 事件增强（2026-06-07）

### 检查范围
全面检查 CLI / SDK / REST API / WebSocket / Skill 五层与成熟 GUI（桌面 ApplicationController）输入输出的差异，重点对比下载流程的实时进度广播和事件字段完整性。

### 发现的差异

| # | 差异 | GUI 行为 | CLI/SDK/API 行为 | 影响 |
|---|---|---|---|---|
| 1 | REST API/WebSocket 直接下载缺少实时进度广播 | GUI 通过 DownloadManager.task_progress 信号实时更新进度条 | REST API `/api/download` 和 WebSocket `download` 使用 SDK `download_video()` 但不广播 `task_progress` 事件 | WebSocket 客户端无法显示下载进度 |
| 2 | `task_finished` 事件缺少 `content_type` 和 `title` | GUI 直接读取 VideoItem 对象获取完整信息 | WebSocket 事件只有 `video_id` 和 `local_path` | 客户端无法获取内容类型和标题 |
| 3 | `video_state_changed` 事件缺少 `local_path` 和 `content_type` | GUI 通过 `_apply_video_state` 更新内存对象 | WebSocket 事件只有 `video_id`/`status`/`progress` | 客户端本地缓存信息不完整 |

### 修复内容

#### 修复1：SDK `download_video` 添加 `progress_callback` 参数

**文件**：`cli/sdk.py`

- `UcrawlSDK.download_video()` 新增 `progress_callback: Callable[[int], None] | None = None` 参数
- 签名：`callback(progress: int) -> None`，进度范围 0-100
- 在 `on_started` 和 `on_progress` 内部回调中调用 `progress_callback`，与 GUI DownloadManager 的 `task_started`/`task_progress` 信号对齐
- 函数式 API `download_video()` 同步添加 `progress_callback` 参数
- 向后兼容：`progress_callback=None` 为默认值，不影响现有调用

#### 修复2：REST API `/api/download` 使用 `progress_callback` 广播进度事件

**文件**：`app/web/server.py`

- 在 `/api/download` 端点中定义 `_on_download_progress(pct)` 回调
- 回调通过 `asyncio.get_running_loop().create_task()` 广播：
  - `task_progress` 事件：`{"video_id": ..., "progress": pct}`（与 WebController `_on_task_progress` 格式对齐）
  - `video_state_changed` 事件：`{"video_id": ..., "status": ..., "progress": pct}`（与 WebController `_apply_video_state` 格式对齐）
- 将 `progress_callback=_on_download_progress` 传入 `sdk.download_video()`

#### 修复3：WebSocket `download` 使用 `progress_callback` 广播进度事件

**文件**：`app/web/server.py`

- 在 WebSocket `download` 处理器中定义 `_on_ws_download_progress(pct)` 回调
- 逻辑与 REST API `/api/download` 完全一致
- 将 `progress_callback=_on_ws_download_progress` 传入 `sdk.download_video()`

#### 修复4：`task_finished` 事件增加 `content_type` 和 `title` 字段

**文件**：`app/web/server.py`、`app/web/controller.py`

- REST API `/api/download` 的 `task_finished` 事件：`{"video_id", "local_path", "content_type", "title"}`
- WebSocket `download` 的 `task_finished` 事件：同上
- WebController `_on_task_finished` 的 `task_finished` 事件：同上（从 `item.meta["content_type"]` 和 `item.title` 读取）
- 向后兼容：新增字段，现有客户端忽略未知字段

#### 修复5：`video_state_changed` 事件增加 `local_path` 和 `content_type`

**文件**：`app/web/server.py`、`app/web/controller.py`

- REST API `/api/download` 和 WebSocket `download` 的 `video_state_changed` 事件在完成/失败状态时包含 `local_path` 和 `content_type`
- WebController `_apply_video_state` 的 `video_state_changed` 事件在 `status in ("✅ 完成", "❌ 失败")` 时包含 `local_path` 和 `content_type`
- 向后兼容：仅在完成/失败状态时额外包含字段，中间状态（进度更新）不包含

#### 修复6：SKILL.md 文档更新

**文件**：`cli/skill/SKILL.md`

- SDK 示例新增 `progress_callback` 用法
- WebSocket 事件类型表更新 `task_progress`、`task_finished`、`video_state_changed` 事件描述
- 注意事项新增 `progress_callback` 和 WebSocket 事件增强说明

### 对齐验证

| 层 | 下载进度 | task_finished 字段 | video_state_changed 字段 |
|---|---|---|---|
| GUI | DownloadManager 信号 → 实时更新 | 直接读取 VideoItem | 直接读取 VideoItem |
| CLI | stderr 输出 / progress_callback | N/A（无 WebSocket） | N/A（无 WebSocket） |
| SDK | progress_callback | N/A（返回 dict） | N/A（无 WebSocket） |
| REST API | progress_callback → task_progress 广播 | video_id + local_path + content_type + title | video_id + status + progress + local_path* + content_type* |
| WebSocket | progress_callback → task_progress 广播 | video_id + local_path + content_type + title | video_id + status + progress + local_path* + content_type* |
| WebController | DownloadManager 信号 → task_progress 广播 | video_id + local_path + content_type + title | video_id + status + progress + local_path* + content_type* |

*注：`local_path` 和 `content_type` 仅在完成/失败状态时包含

### 不影响桌面 GUI 和 WebUI 的保证

1. `progress_callback` 是 SDK 的新增可选参数，默认 `None`，不影响现有调用
2. CLI download 命令不使用 `progress_callback`（使用 `verbose=True` 输出到 stderr）
3. 事件字段增强是向后兼容的（新增字段，现有客户端忽略未知字段）
4. WebController 的事件增强不影响桌面 GUI（GUI 直接读取 VideoItem 对象，不依赖 WebSocket 事件）
5. CLIRunner 不受影响（无 WebSocket 客户端，只更新内存状态）

---

## 第27轮：cli/defaults.py 模块缺失修复与三层校验统一（2026-06-06）

### 检查范围

全面检查 CLI、REST API、SDK、Skill 四层与桌面 GUI 的输入输出差异，重点关注 `cli.defaults` 模块是否完整实现、三层校验逻辑是否统一。

### 发现的问题与修复

#### 修复1（关键）：`cli/defaults.py` 模块缺失导致 ImportError

- **文件**: 新建 `cli/defaults.py`
- **问题**: `cli.defaults` 模块被 7+ 个文件引用（`cli/sdk.py`、`cli/commands/search.py`、`cli/commands/download.py`、`app/web/server.py`、`tests/test_cli_defaults.py` 等），但该模块文件不存在。CLI、SDK、REST API 启动时会直接 ImportError 崩溃。
- **修复**: 创建 `cli/defaults.py`，包含以下函数和常量：
  - `get_platform_defaults(source)` — 从 cfg 读取平台默认配置（与 GUI `read_*_run_options` 对齐）
  - `get_default_save_dir()` — 从 cfg 读取默认保存目录（与 GUI `MainWindow.current_save_dir` 对齐）
  - `validate_config_types(config)` — 校验 config 已知参数类型（与 CLI argparse type 和 SDK `_validate_config` 对齐）
  - `build_missav_proxy_url(proxy_str)` — 委托给 `app.core.plugins.settings_builders.build_missav_proxy_url`
  - `infer_content_type(local_path)` — 根据文件扩展名推断 content_type
  - `DEFAULT_CONFIG` / `_FALLBACK_CONFIG` — 兜底配置常量
- **影响**: CLI/SDK/REST API 现在可以正常启动，所有 `from cli.defaults import ...` 语句不再报错。23 个 `test_cli_defaults` 测试全部通过。

#### 修复2：`get_platform_defaults` douyin timeout 逻辑修正

- **文件**: `cli/defaults.py`
- **问题**: 初始实现使用 `cfg.get("douyin", "search_max_pages", 1) and 10` 表达式，虽然结果正确（始终返回 10），但逻辑不清晰，且读取了错误的 cfg 键名。
- **修复**: 简化为 `timeout: 10`，与 GUI `read_douyin_run_options` 完全对齐（GUI 始终返回 `timeout=10`）。
- **影响**: 代码更清晰，行为与 GUI 完全一致。

#### 修复3：`get_platform_defaults` missav proxy 读取逻辑修正

- **文件**: `cli/defaults.py`
- **问题**: 初始实现从 `cfg.get("missav", "proxy_type")` 读取代理类型再调用 `build_missav_proxy_url` 转换，但 GUI 在用户选择代理时会将完整 URL 保存到 `cfg.proxy_url`，直接读取 `proxy_url` 更准确。
- **修复**: 改为从 `cfg.get("missav", "proxy_url", "http://127.0.0.1:7890")` 直接读取已保存的代理 URL，与 GUI 行为对齐。
- **影响**: CLI/SDK/REST API 的 missav 默认代理与 GUI 完全一致。

#### 修复4：REST API `_validate_config_types` 逻辑统一到 `cli.defaults`

- **文件**: `app/web/server.py` 第148-155行
- **问题**: REST API 有独立的 `_validate_config_types` 实现，与 `cli.defaults.validate_config_types` 逻辑重复，可能导致不一致。
- **修复**: 将 REST API 的 `_validate_config_types` 改为委托给 `cli.defaults.validate_config_types`，确保 CLI/SDK/REST API 三层校验逻辑完全一致。
- **影响**: 未来修改校验逻辑只需改 `cli.defaults` 一处，三层自动同步。

#### 修复5：`validate_config_types` 错误消息使用中文类型名称

- **文件**: `cli/defaults.py`
- **问题**: 初始实现使用 `expected.__name__` 返回英文类型名（如 "int"、"bool"），但测试期望中文类型名（如 "整数"、"布尔值"）。
- **修复**: 添加 `_TYPE_NAMES = {int: "整数", bool: "布尔值", str: "字符串"}` 映射，错误消息使用中文类型名称。
- **影响**: 错误消息更友好，与测试期望一致。

### 已验证的对齐项（无需修改）

以下项目经检查已正确对齐，无需修改：

1. **SDK `search()` config 合并** — 三层合并顺序一致（平台默认 → SDK default_config → per-call config）
2. **SDK `download_video()` config 合并** — 与 `search()` 完全一致，包含 missav proxy 转换
3. **CLI search `_build_config`** — 合并顺序与 SDK/REST API 对齐
4. **CLI download** — 委托给 SDK `download_video()`，由 SDK 内部合并平台默认配置
5. **REST API `_merge_default_config`** — 已委托给 `cli.defaults.get_platform_defaults`
6. **`VideoItem.to_dict()`** — 四层序列化统一，字段完全一致
7. **WebController `_video_item_to_dict`** — 委托给 `VideoItem.to_dict()`
8. **状态转换** — 四层一致（⏳ 等待中 → ⏳ 下载中... → ✅ 完成/❌ 失败/❌ 超时）
9. **download=False** — CLI/SDK/REST API 正确设置 "📋 已收集" 状态
10. **content_type 推断** — SDK 和 REST API 都使用 `cli.defaults.infer_content_type()`
11. **SKILL.md** — 文档与代码行为一致
12. **GUI/WebUI** — 未修改，确认不影响

### 未修改的文件（确认不影响 GUI 和 WebUI）

- `app/controllers/application_controller.py` — 未修改
- `app/web/controller.py` — 未修改
- `app/web/static/` — 未修改
- `app/models/video_item.py` — 未修改
- `app/core/` — 未修改

---

## 第26轮：四层输入输出差异检查与优化（2026-06-06）

### 检查范围

对比 CLI、REST API、SDK、Skill 四层与桌面 GUI（ApplicationController / WebController）的输入输出差异。

### 发现的问题与修复

#### 修复1：SDK `_resolve_selection({})` 空dict行为与 REST API 不一致

- **文件**: `cli/sdk.py` 第320行
- **问题**: SDK `_resolve_selection({})` 返回 `RuleSelection(**{})` → `RuleSelection()` → `all_items=False, _select_rule=None`，而 REST API `_build_selection_strategy({})` 返回 `RuleSelection(all_items=True)`。虽然最终行为相同（都全选），但代码路径不一致。
- **修复**: 在 SDK `_resolve_selection` 中，当 `selection` 为空 dict 时，显式返回 `RuleSelection(all_items=True)`，与 REST API 对齐。
- **影响**: 无功能影响，仅代码路径对齐。

#### 修复2：REST API `/api/download` pending_item 初始状态与 GUI 不一致

- **文件**: `app/web/server.py` 第613-624行
- **问题**: REST API `/api/download` 创建 `pending_item` 时使用 `status="⏳ 下载中..."`，但 GUI 流程是 `item_found → "⏳ 等待中" → task_started → "⏳ 下载中..."`。REST API 跳过了"⏳ 等待中"状态。
- **修复**: 创建 `pending_item` 时使用 `status="⏳ 等待中"`，先广播 `item_found`，再切换到 `"⏳ 下载中..."` 并广播 `task_started` + `video_state_changed`，与 GUI/WebController 事件流对齐。
- **影响**: WebUI 前端现在能正确看到 "⏳ 等待中" → "⏳ 下载中..." 的状态转换。

#### 修复3：WebSocket `download` pending_item 初始状态与 GUI 不一致

- **文件**: `app/web/server.py` 第1275-1286行
- **问题**: 同修复2，WebSocket `download` 消息处理器也跳过了"⏳ 等待中"状态。
- **修复**: 同修复2，与 GUI 事件流对齐。
- **影响**: 同修复2。

#### 修复4：`/api/scan` directory 参数校验顺序修正

- **文件**: `app/web/server.py` 第204-209行
- **问题**: `/api/scan` 先用 `or` 应用默认值，再校验类型。如果传入非字符串 truthy 值（如 `123`），类型校验能捕获；但如果传入非字符串 falsy 值（如 `0`），会静默使用默认值，不报错。
- **修复**: 先校验 `directory` 类型（必须是字符串或 null），再应用默认值，与 `/api/search` 的 `save_dir` 校验逻辑对齐。
- **影响**: 非字符串 directory 参数现在会正确返回错误而非静默使用默认值。

#### 修复5：添加 `_validate_config_types` 辅助函数

- **文件**: `app/web/server.py` 第148-167行
- **问题**: REST API 缺少 config 参数类型校验，SKILL.md 文档描述了 `config.max_items` 等参数的类型校验，但代码未实现。
- **修复**: 添加 `_validate_config_types(user_config)` 函数，校验 `max_items`/`max_pages`/`timeout`（int）、`individual_only`（bool）、`priority`/`proxy`（str）的类型，与 CLI argparse type 和 SDK `_validate_config` 对齐。处理 bool 是 int 子类的边界情况。
- **影响**: REST API 和 WebSocket 现在能正确拒绝无效的 config 参数类型。

### 已验证的对齐项（无需修改）

以下项目经检查已正确对齐，无需修改：

1. **`_build_selection_strategy`** — 已支持 all/first/last/rule/preload/interactive/pipe 全部7种策略，含 select/exclude 类型校验和 choices 二维数组校验
2. **`_merge_default_config`** — 已存在，含 MissAV 代理转换逻辑
3. **`/api/search`** — 已包含完整参数校验（source/keyword 类型、config 校验、selection 校验、timeout/run_timeout、download 布尔转换、平台校验、配置合并）
4. **`/api/crawl/start`** — 已包含完整参数校验（download 参数拒绝、source/keyword 校验、平台校验、爬虫运行检查、config/selection/save_dir 校验、异常回滚）
5. **`/api/crawl/select`** — 已包含 indices 类型校验和爬虫运行检查
6. **`/api/scan`** — 已包含 scan_limit 参数支持和 directory 类型校验
7. **`/api/download`** — 已存在完整实现（参数校验、pending_item 状态管理、SDK 调用、WebSocket 广播、错误处理）
8. **WebSocket `_handle_client_message`** — 已包含所有消息类型的完整参数校验（start_crawl、select_tasks、scan_dir、change_dir、change_theme、change_source、save_config、delete_video、rename_video、download）
9. **SDK `download_video`** — config 合并逻辑与 CLI/REST API 一致（平台默认值 → SDK default_config → per-call config）
10. **SDK `search`** — config 合并逻辑与 CLI/REST API 一致
11. **SDK `scan_directory`** — 参数校验与 REST API `/api/scan` 一致
12. **CLI download/search/scan/interactive/platforms** — 参数与 SDK 方法签名对齐
13. **SKILL.md** — 文档与代码行为一致
14. **四层返回值格式** — 完全一致（status/items/elapsed/error 等字段）
15. **四层错误处理** — 一致（TypeError/ValueError → 参数错误，Exception → 执行错误）
16. **四层 selection 策略** — 完全对齐（7种策略，dict 格式统一）
17. **四层 config 合并** — 顺序一致（平台默认值 → 用户配置）

### 未修改的文件（确认不影响 GUI 和 WebUI）

- `app/controllers/application_controller.py` — 未修改
- `app/web/controller.py` — 未修改
- `app/web/static/` — 未修改
- `app/models/video_item.py` — 未修改
- `app/core/` — 未修改
