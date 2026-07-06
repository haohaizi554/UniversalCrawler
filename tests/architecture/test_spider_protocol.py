from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPIDER_ROOT = PROJECT_ROOT / "app/spiders"


def _spider_modules() -> list[Path]:
    return sorted(
        path
        for path in SPIDER_ROOT.glob("*/spider.py")
        if path.parent.name != "__pycache__"
    )


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _class_defs(path: Path) -> list[ast.ClassDef]:
    return [node for node in _tree(path).body if isinstance(node, ast.ClassDef)]


def _base_names(class_def: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in class_def.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def _assigned_self_attrs(class_def: ast.ClassDef) -> set[str]:
    attrs: set[str] = set()
    for node in ast.walk(class_def):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                attrs.add(target.attr)
    return attrs


class SpiderProtocolArchitectureTests(unittest.TestCase):
    def test_all_platform_spiders_have_three_part_module_structure(self) -> None:
        missing: list[str] = []
        for spider_path in _spider_modules():
            platform_dir = spider_path.parent
            for filename in ("spider.py", "parser.py", "task_builder.py"):
                if not (platform_dir / filename).exists():
                    missing.append(f"{platform_dir.relative_to(PROJECT_ROOT).as_posix()}/{filename}")

        self.assertEqual(missing, [])

    def test_all_spider_classes_inherit_base_spider(self) -> None:
        violations: list[str] = []
        for spider_path in _spider_modules():
            for class_def in _class_defs(spider_path):
                if not class_def.name.endswith("Spider") or class_def.name == "BaseSpider":
                    continue
                if "BaseSpider" not in _base_names(class_def):
                    violations.append(f"{spider_path.relative_to(PROJECT_ROOT).as_posix()}::{class_def.name}")

        self.assertEqual(violations, [])

    def test_all_spider_classes_assign_parser_and_task_builder(self) -> None:
        violations: list[str] = []
        for spider_path in _spider_modules():
            for class_def in _class_defs(spider_path):
                if not class_def.name.endswith("Spider") or class_def.name == "BaseSpider":
                    continue
                attrs = _assigned_self_attrs(class_def)
                missing = {"parser", "task_builder"} - attrs
                if missing:
                    missing_text = ", ".join(sorted(missing))
                    violations.append(f"{spider_path.relative_to(PROJECT_ROOT).as_posix()}::{class_def.name} missing {missing_text}")

        self.assertEqual(violations, [])


@unittest.skip("SpiderRegistry runtime code is not implemented; spider modules are discovered by explicit imports.")
class SpiderRegistryMissingArchitectureTests(unittest.TestCase):
    def test_all_spiders_registered_to_spider_registry(self) -> None:
        raise AssertionError("unreachable")


if __name__ == "__main__":
    unittest.main()
