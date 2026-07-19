"""Tests for release-builder proxy selection and child-process environments."""

from __future__ import annotations

import sys

import pytest

from app.config.settings import proxy_app_options
from app.core.plugins.run_options import build_missav_proxy_url
from tests.support.paths import PROJECT_ROOT


RELEASE_TOOL_ROOT = PROJECT_ROOT / "packaging"
if str(RELEASE_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_TOOL_ROOT))


from release_tool.proxy import (
    PROXY_ENVIRONMENT_VARIABLES,
    ProxySelection,
    build_proxy_environment,
    normalize_proxy_url,
    project_proxy_options,
)


def test_legacy_missav_proxy_builder_delegates_to_generic_normalizer():
    assert build_missav_proxy_url("Clash (7890)") == normalize_proxy_url("Clash (7890)")


def test_project_proxy_options_are_immutable_copies_of_application_options():
    options = project_proxy_options()

    assert isinstance(options, tuple)
    assert options == tuple(proxy_app_options())
    with pytest.raises(TypeError):
        options[0]["label"] = "changed"


def test_system_proxy_choice_preserves_base_environment_without_mutating_it():
    base = {"HTTP_PROXY": "http://old", "NO_PROXY": "localhost"}

    env = build_proxy_environment(ProxySelection.system(), base)

    assert env == base
    assert env is not base
    assert base == {"HTTP_PROXY": "http://old", "NO_PROXY": "localhost"}


def test_direct_proxy_choice_removes_upper_and_lowercase_proxy_variables():
    base = {
        "HTTP_PROXY": "http://old",
        "HTTPS_PROXY": "http://old",
        "ALL_PROXY": "http://old",
        "http_proxy": "http://old",
        "https_proxy": "http://old",
        "all_proxy": "http://old",
        "NO_PROXY": "localhost",
        "no_proxy": "127.0.0.1",
        "UNRELATED": "kept",
    }

    env = build_proxy_environment(ProxySelection.direct(), base)

    assert not set(PROXY_ENVIRONMENT_VARIABLES) & set(env)
    assert env["NO_PROXY"] == "localhost"
    assert env["no_proxy"] == "127.0.0.1"
    assert env["UNRELATED"] == "kept"
    assert "HTTP_PROXY" in base


def test_clash_proxy_choice_sets_all_supported_variables():
    env = build_proxy_environment(ProxySelection(label="Clash (7890)"), {})

    for name in PROXY_ENVIRONMENT_VARIABLES:
        assert env[name] == "http://127.0.0.1:7890"


def test_custom_proxy_choice_sets_all_supported_variables():
    env = build_proxy_environment(
        ProxySelection(label="自定义", endpoint="https://proxy.example:8443"),
        {},
    )

    for name in PROXY_ENVIRONMENT_VARIABLES:
        assert env[name] == "https://proxy.example:8443"


@pytest.mark.parametrize(
    "endpoint",
    ("http://proxy.example", "https://", ":", ""),
)
def test_custom_proxy_choice_rejects_invalid_explicit_endpoints(endpoint: str):
    with pytest.raises(ValueError, match="invalid custom proxy endpoint"):
        build_proxy_environment(ProxySelection(label="自定义", endpoint=endpoint), {})
