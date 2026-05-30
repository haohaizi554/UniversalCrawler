# 接口文档

## 说明

`UniversalCrawlerPro` 原项目为 PyQt6 桌面应用，不直接暴露 Web API。为满足课程中的接口测试与 Postman 技术要求，本目录新增了一个“课程接口适配层”，其底层仍然复用项目真实核心函数：

- `sanitize_filename()`
- `build_media_filename()`

启动命令：

```bash
python coursework/api/mock_api_server.py
```

默认地址：

```text
http://127.0.0.1:8765
```

## 接口一：文件名清洗接口

- 接口名称：文件名清洗
- URL：`/api/v1/files/sanitize`
- 请求方法：`GET`
- 接口类型：查询型接口
- 功能说明：对文件名执行 Windows 兼容清洗，移除非法字符、裁剪尾随点和空格，并在空结果时回退为 `untitled`

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 否 | 原始文件名 |

### 成功响应

状态码：`200`

```json
{
  "code": 0,
  "message": "文件名清洗成功",
  "data": {
    "original": "bad:/name?*.mp4.  ",
    "sanitized": "bad__name__.mp4"
  }
}
```

### 失败响应

状态码：`404`

```json
{
  "code": 404,
  "message": "Not Found",
  "data": {}
}
```

### 其他说明

- 请求方式错误时，返回 `405 Method Not Allowed`
- `name` 为空字符串时，也会返回 `200`，结果为 `untitled`

## 接口二：媒体文件名生成接口

- 接口名称：媒体文件名生成
- URL：`/api/v1/media/build-filename`
- 请求方法：`POST`
- 接口类型：提交型接口
- 功能说明：根据标题、来源、扩展名和标签信息，生成适合本地落盘的媒体文件名

### 请求头

| 名称 | 值 |
| --- | --- |
| `Content-Type` | `application/json` |

### 请求体参数

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 否 | 媒体标题 |
| `source` | string | 是 | 平台来源，例如 `missav`、`douyin` |
| `extension` | string | 否 | 扩展名，支持带点或不带点 |
| `meta` | object | 否 | 附加字段，当前重点使用 `tags` |

### 成功响应

状态码：`200`

```json
{
  "code": 0,
  "message": "媒体文件名生成成功",
  "data": {
    "filename": "CAWD-377 [中文字幕].mp4"
  }
}
```

### 失败响应

状态码：`400`

```json
{
  "code": 4002,
  "message": "缺少 source 参数",
  "data": {}
}
```

```json
{
  "code": 4003,
  "message": "meta 必须为对象",
  "data": {}
}
```

### 其他说明

- JSON 解析失败时返回 `400`
- 请求方式错误时返回 `405`
- `source` 为空时返回 `4002`
- `meta` 非对象时返回 `4003`
