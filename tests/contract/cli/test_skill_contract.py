from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.support.paths import PROJECT_ROOT

class CliSkillContractTests(unittest.TestCase):
    def test_skill_wrapper_runs_outside_repository(self) -> None:
        script = PROJECT_ROOT / "cli" / "skill" / "ucrawl_skill.py"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run(
                [sys.executable, str(script), "--version"],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ucrawl ", result.stdout)

    def test_skill_and_cli_guide_cover_every_supported_platform(self) -> None:
        skill = (PROJECT_ROOT / "cli" / "skill" / "SKILL.md").read_text(encoding="utf-8")
        guide = (PROJECT_ROOT / "docs" / "cli" / "cli-guide.md").read_text(encoding="utf-8")

        for platform in ("douyin", "xiaohongshu", "bilibili", "kuaishou", "missav"):
            with self.subTest(platform=platform):
                self.assertIn(platform, skill)
                self.assertIn(platform, guide)

    def test_skill_uses_canonical_timeout_and_download_syntax(self) -> None:
        text = (PROJECT_ROOT / "cli" / "skill" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("--http-timeout", text)
        self.assertIn("download --source", text)
        self.assertNotIn("--url", text)
        self.assertNotIn("<video_id>", text)

    def test_active_cli_guides_do_not_publish_removed_platform_scan(self) -> None:
        for relative in (
            "README.md",
            "cli/README.md",
            "docs/cli/cli-guide.md",
        ):
            with self.subTest(relative=relative):
                text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("douyin scan", text)
                self.assertNotIn("bilibili scan", text)


if __name__ == "__main__":
    unittest.main()
