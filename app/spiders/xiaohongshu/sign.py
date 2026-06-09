"""Xiaohongshu request signing helpers adapted for the local spider runtime."""

from __future__ import annotations

import hashlib
import json
import random
import time
from typing import Any
from urllib.parse import quote


def generate_trace_id() -> str:
    """Generate a stable 16-char trace id compatible with XHS link tracing."""
    return "".join(random.choice("abcdef0123456789") for _ in range(16))


def _patch_xhshow_get_hash() -> None:
    """Patch xhshow GET signing so query strings participate in a3 hashing.

    MediaCrawler already proved this patch is required for some XHS GET APIs.
    Import is kept local so the module remains importable without xhshow installed.
    """
    from xhshow.core.crypto import CryptoProcessor

    if getattr(CryptoProcessor.build_payload_array, "_ucrawl_xhs_patched", False):
        return

    original_build = CryptoProcessor.build_payload_array

    def patched_build(
        self,
        hex_parameter,
        a1_value,
        app_identifier="xhs-pc-web",
        string_param="",
        timestamp=None,
        sign_state=None,
    ):
        payload = original_build(
            self,
            hex_parameter,
            a1_value,
            app_identifier,
            string_param,
            timestamp,
            sign_state,
        )
        if "{" not in string_param:
            correct_md5_hex = hashlib.md5(string_param.encode("utf-8")).hexdigest()
            correct_md5_bytes = [int(correct_md5_hex[i : i + 2], 16) for i in range(0, 32, 2)]
            seed_byte = payload[4]
            ts_bytes = payload[8:16]
            correct_a3_hash = self._custom_hash_v2(list(ts_bytes) + correct_md5_bytes)
            for idx in range(16):
                payload[128 + idx] = correct_a3_hash[idx] ^ seed_byte
        return payload

    patched_build._ucrawl_xhs_patched = True
    CryptoProcessor.build_payload_array = patched_build


def _build_sign_string(uri: str, data: dict[str, Any] | str | None = None, method: str = "POST") -> str:
    """Build the exact content string expected by the XHS web signer."""
    if method.upper() == "POST":
        if data is None:
            return uri
        if isinstance(data, dict):
            return uri + json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return uri + str(data)

    if not data:
        return uri
    if isinstance(data, dict):
        parts: list[str] = []
        for key, value in data.items():
            if isinstance(value, list):
                value_str = ",".join(str(item) for item in value)
            elif value is None:
                value_str = ""
            else:
                value_str = str(value)
            parts.append(f"{key}={quote(value_str, safe=',')}")
        return f"{uri}?{'&'.join(parts)}"
    return f"{uri}?{data}"


def sign_with_xhshow(
    *,
    uri: str,
    data: dict[str, Any] | str | None = None,
    cookie_str: str = "",
    method: str = "POST",
) -> dict[str, str]:
    """Generate XHS request headers via xhshow."""
    _patch_xhshow_get_hash()

    from xhshow import Xhshow

    client = Xhshow()
    if method.upper() == "POST":
        headers = client.sign_headers_post(
            uri=uri,
            cookies=cookie_str,
            payload=data if isinstance(data, dict) else {},
        )
    else:
        content_string = _build_sign_string(uri, data, method)
        cookie_dict = client._parse_cookies(cookie_str)
        a1_value = cookie_dict.get("a1", "")
        ts = time.time()
        digest = hashlib.md5(content_string.encode("utf-8")).hexdigest()
        payload_array = client.crypto_processor.build_payload_array(
            digest,
            a1_value,
            "xhs-pc-web",
            content_string,
            ts,
        )
        xor_result = client.crypto_processor.bit_ops.xor_transform_array(payload_array)
        config = client.config
        x3_b64 = client.crypto_processor.b64encoder.encode_x3(xor_result[: config.PAYLOAD_LENGTH])
        sig_data = config.SIGNATURE_DATA_TEMPLATE.copy()
        sig_data["x3"] = config.X3_PREFIX + x3_b64
        headers = {
            "x-s": config.XYS_PREFIX
            + client.crypto_processor.b64encoder.encode(
                json.dumps(sig_data, separators=(",", ":"), ensure_ascii=False)
            ),
            "x-s-common": client.sign_xs_common(cookie_dict),
            "x-t": str(client.get_x_t(ts)),
            "x-b3-traceid": client.get_b3_trace_id(),
        }

    return {
        "X-S": headers.get("x-s", ""),
        "X-T": headers.get("x-t", ""),
        "x-S-Common": headers.get("x-s-common", ""),
        "X-B3-Traceid": headers.get("x-b3-traceid", generate_trace_id()),
    }
