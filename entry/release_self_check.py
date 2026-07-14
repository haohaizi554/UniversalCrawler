"""Installed-distribution diagnostics behind the public ``ucrawl-test`` command."""

from __future__ import annotations

import importlib
import importlib.metadata


def _distribution_checks() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    try:
        distribution = importlib.metadata.distribution("ucrawl")
    except importlib.metadata.PackageNotFoundError as exc:
        return [("distribution metadata", False, str(exc))]

    version = distribution.version
    checks.append(("distribution metadata", bool(version), version or "missing version"))

    entry_points = {entry.name for entry in distribution.entry_points}
    required_entries = {"ucrawl", "ucrawl-gui", "ucrawl-test", "ucrawl-test-gui"}
    missing_entries = sorted(required_entries - entry_points)
    checks.append(
        (
            "public commands",
            not missing_entries,
            "ok" if not missing_entries else f"missing: {', '.join(missing_entries)}",
        )
    )

    packaged_files = {str(path).replace("\\", "/") for path in (distribution.files or ())}
    checks.append(
        (
            "web assets",
            "app/web/static/index.html" in packaged_files,
            "app/web/static/index.html",
        )
    )
    tests_leaked = any(path == "tests" or path.startswith("tests/") for path in packaged_files)
    checks.append(("release contents", not tests_leaked, "tests excluded" if not tests_leaked else "tests leaked"))
    return checks


def _module_checks() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    for module_name in (
        "shared.runtime_adapters",
        "shared.runtime_options",
        "shared.selection_base",
        "shared.settings_metadata",
        "entry.test_entry",
    ):
        try:
            importlib.import_module(module_name)
        except (ImportError, RuntimeError, OSError) as exc:
            checks.append((f"import {module_name}", False, str(exc)))
        else:
            checks.append((f"import {module_name}", True, "ok"))
    return checks


def run(*, verbose: bool = False, list_only: bool = False) -> int:
    """Run bounded checks that remain available when source tests are absent."""
    if list_only:
        print("installed  Installed release self-check")
        print("Full development suites are available from a source checkout.")
        return 0

    checks = [*_distribution_checks(), *_module_checks()]
    failed = [check for check in checks if not check[1]]
    print("UCrawl installed release self-check")
    for name, passed, detail in checks:
        if verbose or not passed:
            print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run(verbose=True))
