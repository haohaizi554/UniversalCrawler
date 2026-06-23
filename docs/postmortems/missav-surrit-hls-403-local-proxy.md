# MissAV / surrit HLS 403 与本地代理下载复盘

## 背景

MissAV 视频页能在浏览器正常播放，但把 `surrit.com/.../playlist.m3u8` 直链交给外部下载器时会稳定出现 403。单纯补 `Referer`、`User-Agent`、`Origin`、`Sec-Fetch-*`、`Cookie` 等请求头并不能稳定复现浏览器行为。

## 现象

- 浏览器从 MissAV 页面发起的 surrit HLS 请求返回 200/206。
- 直接访问同一个 surrit m3u8 常见 403。
- Python `curl_cffi` 路径可以下载，但速度慢，且不如 N_m3u8DL-RE 的分片并发和合并能力。
- N_m3u8DL-RE 直接请求 surrit 时仍然可能 403。

## 根因

这不是“少一个请求头”的问题。surrit 对跨站 HLS 请求的校验更接近浏览器会话行为，外部工具直接请求时即使带上表面请求头，也可能缺少浏览器 TLS/HTTP 指纹、会话上下文或请求链路细节。

Python 路径能成功，是因为 `curl_cffi` 可以用 Chrome impersonation 去上游请求；N_m3u8DL-RE 能快，是因为它擅长并发下载、重试和 mux。两者各有一半答案。

## 修复策略

把链路拆成两段：

1. N_m3u8DL-RE 只访问本机 `127.0.0.1` 的 HLS 代理地址。
2. 本地代理用 `curl_cffi` 携带 MissAV 页面 Referer、UA、必要 Cookie，并使用 Chrome impersonation 去访问 surrit。
3. 代理将 playlist 中的 segment、key、init map URL 全部改写成本地代理 URL。
4. N_m3u8DL-RE 继续负责 16 线程下载、重试、自动选流和 MP4 mux。

这样既保留浏览器化上游请求能力，又保留外部工具的下载速度。

## 经验教训

- 不要把受保护 HLS 源直接交给外部工具硬撞；对 MissAV/surrit 这类站点，本地代理是更稳定的边界。
- 请求头截图只能证明浏览器请求形态，不能证明外部工具能复现完整浏览器指纹。
- playlist 缓存必须只缓存真正包含 `#EXTM3U` 的 200/206 响应，不能缓存 403 页面或空响应。
- UI 进度不能只盯最终 mp4 文件。外部工具下载时，最终文件通常在 mux 后才出现，必须从代理转发字节数、分片总数、临时文件大小等渠道获取实时遥测。
- N_m3u8DL-RE 的 MissAV 默认线程数应固定为 16，避免被全局并发配置误降速。

## 后续守则

- MissAV/surrit 默认走本地 HLS 代理 + N_m3u8DL-RE。
- 本地代理需要暴露已服务字节数和分片完成数，作为 GUI/WebUI 下载速度和进度来源。
- 403 排查时要区分三类失败：入口 playlist 403、variant playlist 403、segment/key/init 请求 403。
- 下载链路日志必须记录是否启用本地代理、N 工具线程数、原始 URL、本地代理 URL和 Trace ID。
