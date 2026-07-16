"""Stable repository paths for deeply nested test modules and helpers."""

from pathlib import Path


TESTS_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TESTS_ROOT.parent
