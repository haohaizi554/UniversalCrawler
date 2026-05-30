"""Execute coursework API cases and persist timing evidence."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT / "coursework" / "api" / "execution_results.md"


def http_request(method: str, url: str, payload: dict | None = None) -> tuple[int, dict, float]:
    """执行 `http_request` 对应的业务逻辑。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url=url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            elapsed_ms = (time.perf_counter() - started) * 1000
            return response.status, json.loads(body), elapsed_ms
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        elapsed_ms = (time.perf_counter() - started) * 1000
        return exc.code, json.loads(body), elapsed_ms


def main() -> int:
    """作为脚本入口组织整体执行流程。"""
    base_url = "http://127.0.0.1:8765"
    cases = [
        {
            "id": "API-GET-001",
            "name": "文件名清洗正常场景",
            "method": "GET",
            "url": f"{base_url}/api/v1/files/sanitize?{urlencode({'name': 'bad:/name?*.mp4.  '})}",
            "expected_status": 200,
            "expected_field": ("data", "sanitized", "bad__name__.mp4"),
        },
        {
            "id": "API-POST-001",
            "name": "媒体文件名生成正常场景",
            "method": "POST",
            "url": f"{base_url}/api/v1/media/build-filename",
            "payload": {"title": "CAWD-377", "source": "missav", "extension": "mp4", "meta": {"tags": ["中文字幕"]}},
            "expected_status": 200,
            "expected_field": ("data", "filename", "CAWD-377 [中文字幕].mp4"),
        },
        {
            "id": "API-POST-002",
            "name": "缺少source异常场景",
            "method": "POST",
            "url": f"{base_url}/api/v1/media/build-filename",
            "payload": {"title": "demo", "extension": "mp4", "meta": {}},
            "expected_status": 400,
            "expected_field": ("code", None, 4002),
        },
        {
            "id": "API-PUT-001",
            "name": "请求方式错误场景",
            "method": "PUT",
            "url": f"{base_url}/api/v1/files/sanitize?{urlencode({'name': 'demo'})}",
            "expected_status": 405,
            "expected_field": ("code", None, 405),
        },
    ]

    lines = [
        "# 接口执行结果",
        "",
        "以下结果基于本地课程接口适配层执行，时间单位为毫秒。",
        "",
        "| 用例ID | 名称 | 状态码 | 响应时间(ms) | 校验结果 |",
        "| --- | --- | --- | ---: | --- |",
    ]

    for case in cases:
        status, payload, elapsed_ms = http_request(case["method"], case["url"], case.get("payload"))
        key1, key2, expected = case["expected_field"]
        actual = payload.get(key1) if key2 is None else payload.get(key1, {}).get(key2)
        passed = status == case["expected_status"] and actual == expected
        lines.append(f"| {case['id']} | {case['name']} | {status} | {elapsed_ms:.2f} | {'通过' if passed else '失败'} |")
        lines.append("")
        lines.append(f"## {case['id']} - {case['name']}")
        lines.append("")
        lines.append(f"- 请求方法：`{case['method']}`")
        lines.append(f"- 请求地址：`{case['url']}`")
        if case.get("payload") is not None:
            lines.append(f"- 请求体：`{json.dumps(case['payload'], ensure_ascii=False)}`")
        lines.append(f"- 实际状态码：`{status}`")
        lines.append(f"- 响应时间：`{elapsed_ms:.2f} ms`")
        lines.append(f"- 实际响应：`{json.dumps(payload, ensure_ascii=False)}`")
        lines.append(f"- 校验结论：`{'通过' if passed else '失败'}`")
        lines.append("")

    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    print(f"API execution results saved to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
