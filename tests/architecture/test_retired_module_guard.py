"""Guard the canonical runtime paths after absorbing abandoned extractions."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

RETIRED_MODULES = (
    "app/web/workflow_download_request_service.py",
    "app/web/workflow_download_service.py",
    "app/web/workflow_launch_service.py",
    "app/web/static_router.py",
    "app/services/file_ops.py",
    "app/utils/cookie_sanitizer.py",
)


def test_abandoned_extractions_are_absorbed_into_canonical_runtime_modules() -> None:
    remaining = [relative_path for relative_path in RETIRED_MODULES if (PROJECT_ROOT / relative_path).exists()]

    assert not remaining, (
        "Retired shadow implementations must stay absorbed into their canonical runtime modules: "
        + ", ".join(remaining)
    )
