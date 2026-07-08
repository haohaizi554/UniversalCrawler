from __future__ import annotations

import base64
import hashlib
import json
import random
import struct
import threading
import time
import urllib.parse
from http.cookies import CookieError, SimpleCookie
from typing import Any
from urllib.parse import quote

MAX_32BIT = 0xFFFFFFFF
HEX_CHARS = "abcdef0123456789"
HEX_KEY = (
    "71a302257793271ddd273bcee3e4b98d9d7935e1da33f5765e2ea8afb6dc77a5"
    "1a499d23b67c20660025860cbf13d4540d92497f58686c574e508f46e195634"
    "4f39139bf4faf22a3eef120b79258145b2feb5193b6478669961298e79bedca"
    "646e1a693a926154a5a7a1bd1cf0dedb742f917a747a1e388b234f2277516"
    "db7116035439730fa61e9822a0eca7bff72d8"
)
STANDARD_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
CUSTOM_BASE64_ALPHABET = "ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5"
X3_BASE64_ALPHABET = "MfgqrsbcyzPQRStuvC7mn501HIJBo2DEFTKdeNOwxWXYZap89+/A4UVLhijkl63G"
VERSION_BYTES = [121, 104, 96, 41]
PAYLOAD_LENGTH = 144
A1_LENGTH = 52
APP_ID_LENGTH = 10
MD5_XOR_LENGTH = 8
A3_PREFIX = [2, 97, 51, 16]
TIMESTAMP_LE_LENGTH = 8
ENV_TABLE = [115, 248, 83, 102, 103, 201, 181, 131, 99, 94, 4, 68, 250, 132, 21]
ENV_CHECKS_DEFAULT = [0, 1, 18, 1, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0]
HASH_IV = (1831565813, 461845907, 2246822507, 3266489909)
SIGNATURE_DATA_TEMPLATE = {"x0": "4.2.6", "x1": "xhs-pc-web", "x2": "Windows", "x3": "", "x4": ""}
X3_PREFIX = "mns0301_"
XYS_PREFIX = "XYS_"
B1_SECRET_KEY = "xhswebmplfbt"
PUBLIC_USERAGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0"
)
SIGNATURE_XSCOMMON_TEMPLATE = {
    "s0": 5,
    "s1": "",
    "x0": "1",
    "x1": "4.2.6",
    "x2": "Windows",
    "x3": "xhs-pc-web",
    "x4": "4.86.0",
    "x5": "",
    "x6": "",
    "x7": "",
    "x8": "",
    "x9": -596800761,
    "x10": 0,
    "x11": "normal",
}
FINGERPRINT_CAPABILITY_X37 = "0|0|0|0|0|0|0|0|0|1|0|0|0|0|0|0|0|0|1|0|0|0|0|0"
FINGERPRINT_CAPABILITY_X38 = (
    "0|0|1|0|1|0|0|0|0|0|1|0|1|0|1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0"
)
_FINGERPRINT_CACHE: dict[str, dict[str, Any]] = {}
_FINGERPRINT_LOCK = threading.RLock()


class XiaohongshuLocalSignatureError(RuntimeError):
    """Expected local-signature failure that may be retried through xhshow."""


def _build_crc32_table() -> tuple[int, ...]:
    table: list[int] = []
    for byte_value in range(256):
        item = byte_value
        for _ in range(8):
            item = ((item >> 1) ^ 0xEDB88320) if item & 1 else item >> 1
            item &= MAX_32BIT
        table.append(item)
    return tuple(table)


XHS_CRC32_TABLE = _build_crc32_table()


def generate_trace_id() -> str:
    """Generate a stable 16-char trace id compatible with XHS link tracing."""
    return "".join(random.choice(HEX_CHARS) for _ in range(16))


def _translate_base64(data: bytes | str | bytearray | list[int], alphabet: str) -> str:
    if isinstance(data, str):
        raw = data.encode("utf-8")
    elif isinstance(data, list):
        raw = bytearray(data)
    else:
        raw = bytes(data)
    encoded = base64.b64encode(raw).decode("utf-8")
    return encoded.translate(str.maketrans(STANDARD_BASE64_ALPHABET, alphabet))


def _custom_b64(data: bytes | str | bytearray | list[int]) -> str:
    return _translate_base64(data, CUSTOM_BASE64_ALPHABET)


def _x3_b64(data: bytes | bytearray) -> str:
    return _translate_base64(data, X3_BASE64_ALPHABET)


def _int_to_le_bytes(value: int, length: int = 4) -> list[int]:
    result: list[int] = []
    for _ in range(length):
        result.append(value & 0xFF)
        value >>= 8
    return result


def _rotate_left(value: int, bits: int) -> int:
    return ((value << bits) | (value >> (32 - bits))) & MAX_32BIT


def _custom_hash_v2(input_bytes: list[int]) -> list[int]:
    s0, s1, s2, s3 = HASH_IV
    length = len(input_bytes)
    s0 ^= length
    s1 ^= length << 8
    s2 ^= length << 16
    s3 ^= length << 24
    for index in range(length // 8):
        v0, v1 = struct.unpack("<II", bytes(input_bytes[index * 8 : (index + 1) * 8]))
        s0 = _rotate_left(((s0 + v0) & MAX_32BIT) ^ s2, 7)
        s1 = _rotate_left(((v0 ^ s1) + s3) & MAX_32BIT, 11)
        s2 = _rotate_left(((s2 + v1) & MAX_32BIT) ^ s0, 13)
        s3 = _rotate_left(((s3 ^ v1) + s1) & MAX_32BIT, 17)
    t0 = s0 ^ length
    t1 = s1 ^ t0
    t2 = (s2 + t1) & MAX_32BIT
    t3 = s3 ^ t2
    rot_t0 = _rotate_left(t0, 9)
    rot_t1 = _rotate_left(t1, 13)
    rot_t2 = _rotate_left(t2, 17)
    rot_t3 = _rotate_left(t3, 19)
    s0 = (rot_t0 + rot_t2) & MAX_32BIT
    s1 = rot_t1 ^ rot_t3
    s2 = (rot_t2 + s0) & MAX_32BIT
    s3 = rot_t3 ^ s1
    output: list[int] = []
    for state in (s0, s1, s2, s3):
        output.extend(_int_to_le_bytes(state, 4))
    return output


def _xor_transform(source: list[int]) -> bytearray:
    key_bytes = bytes.fromhex(HEX_KEY)
    output = bytearray(len(source))
    for index, value in enumerate(source):
        output[index] = (value ^ key_bytes[index]) & 0xFF if index < len(key_bytes) else value & 0xFF
    return output


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


def _a3_hash_source(content_string: str) -> str:
    # POST signs the API path for a3; GET signs the full path with query.
    if "{" in content_string:
        return content_string.split("{", 1)[0]
    return content_string


def _build_payload_array(
    hex_parameter: str,
    a1_value: str,
    *,
    app_identifier: str = "xhs-pc-web",
    content_string: str = "",
    timestamp: float | None = None,
) -> list[int]:
    timestamp = time.time() if timestamp is None else timestamp
    seed = random.randint(0, MAX_32BIT)
    seed_byte = seed & 0xFF
    payload = list(VERSION_BYTES)
    payload.extend(_int_to_le_bytes(seed, 4))
    ts_bytes = _int_to_le_bytes(int(timestamp * 1000), TIMESTAMP_LE_LENGTH)
    payload.extend(ts_bytes)
    time_offset = random.randint(10, 50)
    payload.extend(_int_to_le_bytes(int((timestamp - time_offset) * 1000), TIMESTAMP_LE_LENGTH))
    payload.extend(_int_to_le_bytes(random.randint(15, 50), 4))
    payload.extend(_int_to_le_bytes(random.randint(1000, 1200), 4))
    payload.extend(_int_to_le_bytes(len(content_string.encode("utf-8")), 4))

    md5_bytes = bytes.fromhex(hex_parameter)
    payload.extend([md5_bytes[index] ^ seed_byte for index in range(MD5_XOR_LENGTH)])

    a1_bytes = a1_value.encode("utf-8")[:A1_LENGTH].ljust(A1_LENGTH, b"\x00")
    payload.append(len(a1_bytes))
    payload.extend(a1_bytes)

    app_bytes = app_identifier.encode("utf-8")[:APP_ID_LENGTH].ljust(APP_ID_LENGTH, b"\x00")
    payload.append(len(app_bytes))
    payload.extend(app_bytes)

    payload.extend([1, seed_byte ^ ENV_TABLE[0]])
    payload.extend([ENV_TABLE[index] ^ ENV_CHECKS_DEFAULT[index] for index in range(1, 15)])

    a3_source = _a3_hash_source(content_string)
    a3_md5 = hashlib.md5(a3_source.encode("utf-8")).hexdigest()
    a3_md5_bytes = [int(a3_md5[index : index + 2], 16) for index in range(0, 32, 2)]
    payload.extend(A3_PREFIX + [value ^ seed_byte for value in _custom_hash_v2(ts_bytes + a3_md5_bytes)])
    return payload


def _parse_cookies(cookies: dict[str, Any] | str) -> dict[str, str]:
    if isinstance(cookies, dict):
        return {str(key): str(value) for key, value in cookies.items()}
    jar = SimpleCookie()
    jar.load(cookies or "")
    return {key: morsel.value for key, morsel in jar.items()}


def _signed_crc32(value: str) -> int:
    crc = 0xFFFFFFFF
    table = XHS_CRC32_TABLE
    for ch in value:
        crc = (table[((crc & 0xFF) ^ (ord(ch) & 0xFF)) & 0xFF] ^ (crc >> 8)) & MAX_32BIT
    unsigned = ((MAX_32BIT ^ crc) ^ 0xEDB88320) & MAX_32BIT
    return unsigned - 0x100000000 if unsigned & 0x80000000 else unsigned


def _fingerprint_seed(cookie_dict: dict[str, str]) -> str:
    source = "|".join(
        cookie_dict.get(key, "")
        for key in ("a1", "web_session", "webId", "gid", "gid.sign")
    )
    if not source.strip("|"):
        source = ";".join(f"{key}={value}" for key, value in sorted(cookie_dict.items()))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _stable_hex(seed: str, label: str, length: int) -> str:
    digest = hashlib.sha256(f"{seed}:{label}".encode("utf-8")).hexdigest()
    while len(digest) < length:
        digest += hashlib.sha256(digest.encode("utf-8")).hexdigest()
    return digest[:length]


def _cached_fingerprint_static(cookie_dict: dict[str, str]) -> dict[str, Any]:
    seed = _fingerprint_seed(cookie_dict)
    cache_key = seed[:32]
    with _FINGERPRINT_LOCK:
        cached = _FINGERPRINT_CACHE.get(cache_key)
        if cached is not None:
            return dict(cached)

        rng = random.Random(int(seed[:16], 16))
        static = {
            "x33": "0",
            "x34": "0",
            "x35": "0",
            "x36": str(rng.randint(1, 20)),
            "x37": FINGERPRINT_CAPABILITY_X37,
            "x38": FINGERPRINT_CAPABILITY_X38,
            "x39": 0,
            "x42": "3.4.4",
            "x43": _stable_hex(seed, "canvas", 8),
            "x45": "__SEC_CAV__1-1-1-1-1|__SEC_WSA__|",
            "x46": "false",
            "x48": "",
            "x49": "{list:[],type:}",
            "x50": "",
            "x51": "",
            "x52": "",
            "x82": "_0x17a2|_0x1954",
        }
        _FINGERPRINT_CACHE[cache_key] = dict(static)
        return static


def _minimal_fingerprint(cookie_dict: dict[str, str]) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    fingerprint = _cached_fingerprint_static(cookie_dict)
    fingerprint["x44"] = str(now_ms)
    fingerprint["x57"] = "; ".join(f"{key}={value}" for key, value in cookie_dict.items())
    fingerprint["x1"] = PUBLIC_USERAGENT
    return fingerprint


def _rc4_crypt(key: bytes, data: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 0xFF
        state[i], state[j] = state[j], state[i]
    i = 0
    j = 0
    output = bytearray()
    for byte in data:
        i = (i + 1) & 0xFF
        j = (j + state[i]) & 0xFF
        state[i], state[j] = state[j], state[i]
        k = state[(state[i] + state[j]) & 0xFF]
        output.append(byte ^ k)
    return bytes(output)


def _generate_b1(fingerprint: dict[str, Any]) -> str:
    b1_fp = {
        "x33": fingerprint["x33"],
        "x34": fingerprint["x34"],
        "x35": fingerprint["x35"],
        "x36": fingerprint["x36"],
        "x37": fingerprint["x37"],
        "x38": fingerprint["x38"],
        "x39": fingerprint["x39"],
        "x42": fingerprint["x42"],
        "x43": fingerprint["x43"],
        "x44": fingerprint["x44"],
        "x45": fingerprint["x45"],
        "x46": fingerprint["x46"],
        "x48": fingerprint["x48"],
        "x49": fingerprint["x49"],
        "x50": fingerprint["x50"],
        "x51": fingerprint["x51"],
        "x52": fingerprint["x52"],
        "x82": fingerprint["x82"],
    }
    compact = json.dumps(b1_fp, separators=(",", ":"), ensure_ascii=False)
    cipher_text = _rc4_crypt(B1_SECRET_KEY.encode(), compact.encode("utf-8")).decode("latin1")
    encoded = urllib.parse.quote(cipher_text, safe="!*'()~_-")
    byte_values: list[int] = []
    for chunk in encoded.split("%")[1:]:
        byte_values.append(int(chunk[:2], 16))
        byte_values.extend(ord(char) for char in chunk[2:])
    return _custom_b64(bytearray(byte_values))


def _sign_xs_common(cookie_dict: dict[str, str]) -> str:
    a1_value = cookie_dict["a1"]
    fingerprint = _minimal_fingerprint(cookie_dict)
    b1 = _generate_b1(fingerprint)
    payload = dict(SIGNATURE_XSCOMMON_TEMPLATE)
    payload["x5"] = a1_value
    payload["x8"] = b1
    payload["x9"] = _signed_crc32(b1)
    return _custom_b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def sign_with_local_algorithm(
    *,
    uri: str,
    data: dict[str, Any] | str | None = None,
    cookie_str: str = "",
    method: str = "POST",
    timestamp: float | None = None,
) -> dict[str, str]:
    """Generate XHS request headers without xhshow."""
    try:
        timestamp = time.time() if timestamp is None else timestamp
        cookie_dict = _parse_cookies(cookie_str)
        a1_value = cookie_dict.get("a1", "")
        if not a1_value:
            raise XiaohongshuLocalSignatureError("missing a1 cookie for Xiaohongshu signature")
        content_string = _build_sign_string(uri, data, method)
        digest = hashlib.md5(content_string.encode("utf-8")).hexdigest()
        payload_array = _build_payload_array(
            digest,
            a1_value,
            content_string=content_string,
            timestamp=timestamp,
        )
        x3 = _x3_b64(_xor_transform(payload_array)[:PAYLOAD_LENGTH])
        signature_data = dict(SIGNATURE_DATA_TEMPLATE)
        signature_data["x3"] = X3_PREFIX + x3
        x_s = XYS_PREFIX + _custom_b64(json.dumps(signature_data, separators=(",", ":"), ensure_ascii=False))
        return {
            "X-S": x_s,
            "X-T": str(int(timestamp * 1000)),
            "x-S-Common": _sign_xs_common(cookie_dict),
            "X-B3-Traceid": generate_trace_id(),
        }
    except XiaohongshuLocalSignatureError:
        raise
    except (CookieError, KeyError, UnicodeError, ValueError) as exc:
        raise XiaohongshuLocalSignatureError("local Xiaohongshu signature failed") from exc


def _patch_xhshow_get_hash() -> None:
    """Patch xhshow GET signing so query strings participate in a3 hashing."""
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


def sign_with_xhshow(
    *,
    uri: str,
    data: dict[str, Any] | str | None = None,
    cookie_str: str = "",
    method: str = "POST",
) -> dict[str, str]:
    """Generate XHS request headers via xhshow fallback."""
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


def sign_xiaohongshu_headers(
    *,
    uri: str,
    data: dict[str, Any] | str | None = None,
    cookie_str: str = "",
    method: str = "POST",
) -> dict[str, str]:
    """Generate XHS request headers with local code first and xhshow as fallback."""
    try:
        return sign_with_local_algorithm(uri=uri, data=data, cookie_str=cookie_str, method=method)
    except XiaohongshuLocalSignatureError:
        return sign_with_xhshow(uri=uri, data=data, cookie_str=cookie_str, method=method)
