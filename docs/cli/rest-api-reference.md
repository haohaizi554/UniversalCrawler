# UCrawl REST API 参考

Web 服务启动后暴露的 HTTP API。本文档列出所有可用端点。

## 启动

```bash
# 默认启动 (端口 8000)
python web_main.py

# 自定义端口
python web_main.py --port 9000

# 启动时注入脚本
python web_main.py --script my_automation.py --script-arg target=douyin

# 无 Qt 模式（仅 API，爬虫功能不可用）
python web_main.py --no-qt
```

服务地址：`http://localhost:8000`（或自定义端口）

## 端点列表

### 健康检查

#### GET /api/ping

健康检查端点。

**响应**：
```json
{"status": "ok", "version": "3.6.14"}
```

### 平台

#### GET /api/platforms

列出所有可用平台。

**响应**：
```json
[
  {
    "id": "douyin",
    "name": "抖音",
    "description": "...",
    "settings": [...]
  }
]
```

### 爬虫控制

#### POST /api/crawl/start

启动爬虫。

**请求体**：
```json
{
  "source": "douyin",
  "keyword": "测试",
  "config": {
    "max_items": 20,
    "max_pages": 1
  },
  "save_dir": "downloads"
}
```

**响应**：
```json
{"status": "ok", "message": "爬虫已启动"}
```

#### POST /api/crawl/stop

停止爬虫。

**响应**：
```json
{"status": "ok"}
```

#### POST /api/crawl/select

爬虫扫描后用户选择结果（替代 WebSocket 的 select_tasks 消息）。

**请求体**：
```json
{"indices": [0, 2, 5]}
```

`indices` 为 `null` 表示取消。

**响应**：
```json
{"status": "ok"}
```

### 目录与文件

#### POST /api/dir/change

切换保存目录（自动扫描）。

**请求体**：
```json
{"directory": "./downloads"}
```

**响应**：
```json
{
  "status": "ok",
  "directory": "./downloads",
  "items": [...],
  "total_count": 100,
  "video_count": 90,
  "image_count": 10,
  "message": "已加载 100 个本地文件"
}
```

#### POST /api/scan

扫描本地目录。

**请求体**：
```json
{
  "directory": "./downloads",
  "scan_limit": 1000
}
```

**响应**：同 `/api/dir/change`

### 视频操作

#### POST /api/video/delete

删除视频。

**请求体**：
```json
{"video_id": "v_abc123"}
```

#### POST /api/video/rename

重命名视频。

**请求体**：
```json
{
  "video_id": "v_abc123",
  "new_title": "新标题"
}
```

#### GET /api/media/{video_id}

获取媒体文件（用于在浏览器中播放视频/图片）。

**路径参数**：
- `video_id`：视频 ID

**响应**：媒体文件二进制流

### 主题

#### POST /api/theme

切换主题。

**请求体**：
```json
{"theme": "dark"}  // 或 "light"
```

### 工具

#### GET /api/log/latest

获取最新日志文件内容。

**响应**：日志文件内容（文本）

#### GET /api/log/errors

获取错误摘要。

**响应**：错误信息列表（JSON）

#### GET /api/config

获取完整配置。

**响应**：
```json
{
  "common": {
    "save_directory": "downloads",
    "theme": "dark",
    "last_source": "douyin"
  },
  "download": {
    "max_concurrent": 3,
    "local_scan_limit": 1000
  }
}
```

## WebSocket 事件

Web 服务同时暴露 `/ws` WebSocket 端点，用于实时推送事件。客户端代码示例：

```javascript
const ws = new WebSocket("ws://localhost:8000/ws");
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  switch(msg.type) {
    case "log": console.log(msg.data.message); break;
    case "item_found": addToQueue(msg.data); break;
    case "select_tasks": /* 显示选择弹窗 */; break;
    // ...
  }
};
```

### 事件类型

| 事件 | 数据 | 说明 |
|---|---|---|
| `log` | `{"message": "..."}` | 日志消息 |
| `item_found` | `{id, url, title, ...}` | 找到新视频 |
| `scan_result` | `{total_count, ...}` | 扫描完成 |
| `clear_videos` | `{directory}` | 清空列表 |
| `select_tasks` | `{items, prompt}` | 请求用户选择 |
| `crawl_state` | `{is_running: bool}` | 爬虫状态变化 |
| `task_started` | `{video_id, local_path}` | 下载开始 |
| `task_progress` | `{video_id, progress}` | 下载进度 |
| `task_finished` | `{video_id, local_path}` | 下载完成 |
| `task_error` | `{video_id, error}` | 下载错误 |
| `video_renamed` | `{video_id, new_title}` | 重命名完成 |
| `video_removed` | `{video_id}` | 删除完成 |
| `theme_changed` | `{theme}` | 主题切换 |

## 错误码

| 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

## CORS

所有 `/api/*` 端点允许跨域（`Access-Control-Allow-Origin: *`），可在浏览器中直接调用。
