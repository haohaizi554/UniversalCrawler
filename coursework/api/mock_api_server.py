"""Minimal HTTP adapter for coursework API and Selenium exercises."""

from __future__ import annotations

import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.filenames import build_media_filename, sanitize_filename


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Coursework UI Demo</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; line-height: 1.6; }
    a { display: block; margin: 12px 0; color: #0b57d0; text-decoration: none; }
    .card { border: 1px solid #ddd; border-radius: 12px; padding: 16px; max-width: 760px; }
  </style>
</head>
<body>
  <div class="card">
    <h1 id="home-title">UniversalCrawlerPro Coursework UI Demo</h1>
    <p>该页面用于满足软件测试课程中的 Selenium 自动化要求，底层逻辑复用项目真实文件名工具函数。</p>
    <a id="nav-sanitize" href="/ui/sanitize">场景一：文件名清洗</a>
    <a id="nav-build" href="/ui/build-filename">场景二：媒体文件名生成</a>
  </div>
</body>
</html>
"""


SANITIZE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>文件名清洗场景</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; }
    label, input, button { display: block; margin: 8px 0; }
    #result-card { margin-top: 16px; padding: 12px; border: 1px solid #ddd; border-radius: 8px; }
  </style>
</head>
<body>
  <a id="back-home" href="/">返回首页</a>
  <h1 id="scene-title">文件名清洗场景</h1>
  <label for="name-input">原始文件名</label>
  <input id="name-input" type="text" value="">
  <button id="sanitize-btn" type="button">执行清洗</button>
  <div id="result-card">
    <p id="status-text">等待执行</p>
    <p id="sanitized-result"></p>
  </div>
  <script>
    document.getElementById('sanitize-btn').addEventListener('click', async () => {
      const raw = document.getElementById('name-input').value;
      const response = await fetch('/api/v1/files/sanitize?name=' + encodeURIComponent(raw));
      const data = await response.json();
      document.getElementById('status-text').textContent = data.message;
      document.getElementById('sanitized-result').textContent = data.data.sanitized;
    });
  </script>
</body>
</html>
"""


BUILD_FILENAME_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>媒体文件名生成场景</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 32px; }
    label, input, button, select { display: block; margin: 8px 0; }
    #filename-card { margin-top: 16px; padding: 12px; border: 1px solid #ddd; border-radius: 8px; }
  </style>
</head>
<body>
  <a id="back-home" href="/">返回首页</a>
  <h1 id="build-scene-title">媒体文件名生成场景</h1>
  <label for="title-input">标题</label>
  <input id="title-input" type="text" value="CAWD-377">
  <label for="source-input">来源</label>
  <input id="source-input" type="text" value="missav">
  <label for="extension-input">扩展名</label>
  <input id="extension-input" type="text" value="mp4">
  <label for="tags-input">标签（逗号分隔）</label>
  <input id="tags-input" type="text" value="中文字幕">
  <button id="build-btn" type="button">生成文件名</button>
  <div id="filename-card">
    <p id="build-status">等待执行</p>
    <p id="filename-result"></p>
  </div>
  <script>
    document.getElementById('build-btn').addEventListener('click', async () => {
      const payload = {
        title: document.getElementById('title-input').value,
        source: document.getElementById('source-input').value,
        extension: document.getElementById('extension-input').value,
        meta: { tags: document.getElementById('tags-input').value.split(',').map(v => v.trim()).filter(Boolean) }
      };
      const response = await fetch('/api/v1/media/build-filename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      document.getElementById('build-status').textContent = data.message;
      document.getElementById('filename-result').textContent = data.data.filename;
    });
  </script>
</body>
</html>
"""


class CourseworkHandler(BaseHTTPRequestHandler):
    """封装 `CourseworkHandler` 在 `coursework/api/mock_api_server.py` 中承担的核心逻辑。"""
    server_version = "CourseworkMockApi/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        """提供 `_send_json` 对应的内部辅助逻辑，供 `CourseworkHandler` 使用。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        """提供 `_send_html` 对应的内部辅助逻辑，供 `CourseworkHandler` 使用。"""
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        """提供 `_read_json` 对应的内部辅助逻辑，供 `CourseworkHandler` 使用。"""
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        return json.loads(raw or "{}")

    def do_OPTIONS(self) -> None:
        """执行 `do_OPTIONS` 对应的业务逻辑，供 `CourseworkHandler` 使用。"""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        """执行 `do_GET` 对应的业务逻辑，供 `CourseworkHandler` 使用。"""
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(INDEX_HTML)
            return
        if parsed.path == "/ui/sanitize":
            self._send_html(SANITIZE_HTML)
            return
        if parsed.path == "/ui/build-filename":
            self._send_html(BUILD_FILENAME_HTML)
            return
        if parsed.path == "/api/v1/files/sanitize":
            query = parse_qs(parsed.query)
            raw_name = query.get("name", [""])[0]
            sanitized = sanitize_filename(raw_name)
            self._send_json(
                HTTPStatus.OK,
                {
                    "code": 0,
                    "message": "文件名清洗成功",
                    "data": {"original": raw_name, "sanitized": sanitized},
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"code": 404, "message": "Not Found", "data": {}})

    def do_POST(self) -> None:
        """执行 `do_POST` 对应的业务逻辑，供 `CourseworkHandler` 使用。"""
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/media/build-filename":
            self._send_json(HTTPStatus.NOT_FOUND, {"code": 404, "message": "Not Found", "data": {}})
            return
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"code": 4001, "message": "JSON 解析失败", "data": {}})
            return

        title = payload.get("title", "")
        source = payload.get("source", "")
        extension = payload.get("extension", ".mp4")
        meta = payload.get("meta", {})

        if not source:
            self._send_json(HTTPStatus.BAD_REQUEST, {"code": 4002, "message": "缺少 source 参数", "data": {}})
            return
        if meta is not None and not isinstance(meta, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"code": 4003, "message": "meta 必须为对象", "data": {}})
            return

        filename = build_media_filename(title, source, extension, meta or {})
        self._send_json(
            HTTPStatus.OK,
            {
                "code": 0,
                "message": "媒体文件名生成成功",
                "data": {"filename": filename},
            },
        )

    def do_PUT(self) -> None:
        """执行 `do_PUT` 对应的业务逻辑，供 `CourseworkHandler` 使用。"""
        self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"code": 405, "message": "Method Not Allowed", "data": {}})

    def log_message(self, format: str, *args) -> None:
        """执行 `log_message` 对应的业务逻辑，供 `CourseworkHandler` 使用。"""
        return


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    """执行当前对象或脚本的主流程。"""
    server = ThreadingHTTPServer((host, port), CourseworkHandler)
    print(f"Coursework mock api server running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
