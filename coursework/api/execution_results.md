# 接口执行结果

以下结果基于本地课程接口适配层执行，时间单位为毫秒。

| 用例ID | 名称 | 状态码 | 响应时间(ms) | 校验结果 |
| --- | --- | --- | ---: | --- |
| API-GET-001 | 文件名清洗正常场景 | 200 | 29.41 | 通过 |
| API-POST-001 | 媒体文件名生成正常场景 | 200 | 13.27 | 通过 |
| API-POST-002 | 缺少source异常场景 | 400 | 18.18 | 通过 |
| API-PUT-001 | 请求方式错误场景 | 405 | 15.47 | 通过 |

## 明细记录

## API-GET-001 - 文件名清洗正常场景

- 请求方法：`GET`
- 请求地址：`http://127.0.0.1:8765/api/v1/files/sanitize?name=bad%3A%2Fname%3F%2A.mp4.++`
- 实际状态码：`200`
- 响应时间：`29.41 ms`
- 实际响应：`{"code": 0, "message": "文件名清洗成功", "data": {"original": "bad:/name?*.mp4.  ", "sanitized": "bad__name__.mp4"}}`
- 校验结论：`通过`

## API-POST-001 - 媒体文件名生成正常场景

- 请求方法：`POST`
- 请求地址：`http://127.0.0.1:8765/api/v1/media/build-filename`
- 请求体：`{"title": "CAWD-377", "source": "missav", "extension": "mp4", "meta": {"tags": ["中文字幕"]}}`
- 实际状态码：`200`
- 响应时间：`13.27 ms`
- 实际响应：`{"code": 0, "message": "媒体文件名生成成功", "data": {"filename": "CAWD-377 [中文字幕].mp4"}}`
- 校验结论：`通过`

## API-POST-002 - 缺少source异常场景

- 请求方法：`POST`
- 请求地址：`http://127.0.0.1:8765/api/v1/media/build-filename`
- 请求体：`{"title": "demo", "extension": "mp4", "meta": {}}`
- 实际状态码：`400`
- 响应时间：`18.18 ms`
- 实际响应：`{"code": 4002, "message": "缺少 source 参数", "data": {}}`
- 校验结论：`通过`

## API-PUT-001 - 请求方式错误场景

- 请求方法：`PUT`
- 请求地址：`http://127.0.0.1:8765/api/v1/files/sanitize?name=demo`
- 实际状态码：`405`
- 响应时间：`15.47 ms`
- 实际响应：`{"code": 405, "message": "Method Not Allowed", "data": {}}`
- 校验结论：`通过`

