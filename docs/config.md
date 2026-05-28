# 配置说明

## 配置入口

项目配置统一由 `app/config/settings.py` 管理，运行时通常读取根目录或用户目录中的 `config.json`。

## 常见配置分组

### `common`

- `save_directory`：默认下载目录。
- `last_source`：上次选择的平台。
- `theme`：界面主题。

### `download`

- `max_concurrent`：最大并发下载数。
- `local_scan_limit`：本地媒体扫描上限。
- `max_retries`：下载重试次数。
- `chunk_size`：流式下载块大小。

### `bilibili`

- `api_workers`：B 站详情解析并发度。
- `max_pages`：空间页或搜索页最大翻页数。

### `missav`

- `proxy_url`：代理设置。
- `priority`：中文字幕 / 无码优先策略。
- `individual_only`：是否只抓单体。

### `auth`

- 各平台 Cookie 文件路径。
- 用于浏览器登录后恢复会话。

## 维护建议

- 新字段必须提供默认值与兼容读取逻辑。
- 不同平台特有字段尽量收口到各自分组，不混入 `common`。
- 如果字段会直接影响爬虫流程或下载路径，请同步补测试。
- 变更配置结构后，记得更新 UI 读取逻辑与文档。
