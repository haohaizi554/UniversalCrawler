# 最近错误摘要

- 时间: 2026-05-27 05:39:53
- 模块: BiliAPI
- 动作: check_login
- 状态码: 未提供
- 错误分级: P2-高
- 追踪ID: 未提供
- 错误说明: boom

## 自动建议结论
- 问题大概率出在 Bilibili 接口取流或音视频流下载阶段，建议先检查 get_play_url 和 stream_* 记录。

## 上下文
- cookie_path: bili_auth.json

## 关键详情
- exception_type: RequestException

## 优先排查
- 先用追踪ID在 latest_debug.log 中全文搜索，查看同一任务前后的 API、入队、下载和合并记录。
- 重点检查 `API::get_play_url`、`stream_video`、`stream_audio` 和 `ffmpeg` 记录是否连续。
- 如果是播放流失败，优先确认 `audio_url/video_url` 是否为空、Cookie 是否失效、画质是否受限。
