"""面向 UI 的容量格式化边界测试。"""

from __future__ import annotations

import pytest

from app.utils.formatting import format_size


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [
        (0, "0 B"),
        (-1, "Unknown"),
        (1, "1.0 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024**2, "1.0 MB"),
        (1024**5, "1.0 PB"),
        (1024**6, "1024.0 PB"),
    ],
)
def test_format_size_handles_zero_invalid_boundaries_and_unit_cap(
    size_bytes: int,
    expected: str,
) -> None:
    assert format_size(size_bytes) == expected
