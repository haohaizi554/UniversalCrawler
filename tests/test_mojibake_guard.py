from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("app", "tests")
SCAN_SUFFIXES = {".py", ".js", ".json", ".md"}
KNOWN_MOJIBAKE_SNIPPETS = (
    "涓嬭",
    "浠诲姟",
    "澶辫触",
    "搴旂敤",
    "寮€濮",
    "涓荤獥",
    "鐢ㄦ埛",
    "灏忕孩涔",
    "瑙嗛",
)


def test_source_text_does_not_contain_known_mojibake_literals() -> None:
    offenders: list[str] = []
    guard_file = Path(__file__).resolve()
    for root_name in SCAN_ROOTS:
        for path in (PROJECT_ROOT / root_name).rglob("*"):
            if path.resolve() == guard_file or path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for snippet in KNOWN_MOJIBAKE_SNIPPETS:
                if snippet in text:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {snippet}")

    assert offenders == []
