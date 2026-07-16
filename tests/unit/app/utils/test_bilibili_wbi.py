"""Bilibili WBI 密钥解析、签名和缓存生命周期测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.utils import bilibili_wbi
from app.utils.bilibili_wbi import (
    NAV_URL,
    BilibiliWbiKeys,
    BilibiliWbiSigner,
    extract_wbi_keys_from_nav_data,
    make_mixin_key,
    sign_wbi_params,
)


IMG_KEY = "7cd084941338484aae1ad9425b84077c"
SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"


@pytest.mark.parametrize("payload", [None, {}, {"wbi_img": None}, {"wbi_img": {}}])
def test_extract_wbi_keys_rejects_incomplete_nav_payload(payload: object) -> None:
    assert extract_wbi_keys_from_nav_data(payload) is None


def test_extract_wbi_keys_strips_url_path_and_extension() -> None:
    keys = extract_wbi_keys_from_nav_data(
        {
            "wbi_img": {
                "img_url": f"https://i0.hdslb.com/bfs/wbi/{IMG_KEY}.png",
                "sub_url": f"https://i0.hdslb.com/bfs/wbi/{SUB_KEY}.png?ignored=1",
            }
        }
    )

    assert keys == BilibiliWbiKeys(IMG_KEY, SUB_KEY)


def test_short_keys_leave_parameters_unsigned() -> None:
    assert make_mixin_key("short", "keys") == ""
    assert sign_wbi_params({"page": 2}, "short", "keys", now=1) == {"page": "2"}


def test_signer_fetches_nav_with_transport_options_and_caches_keys() -> None:
    calls: list[tuple[str, dict]] = []

    @dataclass
    class Response:
        def json(self) -> dict:
            return {
                "data": {
                    "wbi_img": {
                        "img_url": f"https://example.test/{IMG_KEY}.png",
                        "sub_url": f"https://example.test/{SUB_KEY}.png",
                    }
                }
            }

    def request_get(url: str, **kwargs: object) -> Response:
        calls.append((url, kwargs))
        return Response()

    signer = BilibiliWbiSigner(ttl_seconds=120)
    keys = signer.ensure_keys(
        request_get,
        headers={"User-Agent": "test"},
        timeout=3,
        proxies={"https": "http://127.0.0.1:7890"},
    )

    assert keys == BilibiliWbiKeys(IMG_KEY, SUB_KEY)
    assert signer.ensure_keys(lambda *_args, **_kwargs: pytest.fail("cache miss")) == keys
    assert calls == [
        (
            NAV_URL,
            {
                "timeout": 3,
                "headers": {"User-Agent": "test"},
                "proxies": {"https": "http://127.0.0.1:7890"},
            },
        )
    ]


def test_signer_clear_and_expiry_invalidate_cached_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter((100.0, 120.0, 161.0))
    monkeypatch.setattr(bilibili_wbi.time, "monotonic", lambda: next(clock))
    signer = BilibiliWbiSigner(ttl_seconds=60)

    signer.set_keys(IMG_KEY, SUB_KEY)
    assert signer.current_keys() == BilibiliWbiKeys(IMG_KEY, SUB_KEY)
    assert signer.current_keys() is None
    signer.clear()
    assert signer.current_keys() is None


def test_signer_returns_original_parameters_when_refresh_fails() -> None:
    signer = BilibiliWbiSigner()

    params, signed = signer.sign_params(
        {"page": 1},
        request_get=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )

    assert params == {"page": 1}
    assert signed is False


def test_signer_uses_preloaded_keys_without_network() -> None:
    signer = BilibiliWbiSigner()
    signer.set_keys(IMG_KEY, SUB_KEY)

    params, signed = signer.sign_params({"foo": "114"}, now=1_700_000_000)

    assert signed is True
    assert params["wts"] == "1700000000"
    assert len(params["w_rid"]) == 32
