from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GitHubActionsWorkflowTests(unittest.TestCase):
    def test_python_workflow_uses_project_pytest_entrypoint(self) -> None:
        workflow = PROJECT_ROOT / ".github" / "workflows" / "python-tests.yml"
        source = workflow.read_text(encoding="utf-8")

        self.assertIn("runs-on: windows-latest", source)
        self.assertIn("python -X faulthandler -m pytest -q", source)
        self.assertNotIn("python -m unittest discover", source)
        self.assertNotIn("runs-on: ubuntu-latest", source)
        self.assertNotIn("sudo apt-get", source)
        self.assertNotIn("xvfb-run", source)
        self.assertIn("QT_QPA_PLATFORM: offscreen", source)
        self.assertIn('PYTHONFAULTHANDLER: "1"', source)
        self.assertIn("python -m playwright install chromium", source)

    def test_runtime_requirements_exclude_optional_report_and_fedora_tools(self) -> None:
        requirements = PROJECT_ROOT / "requirements.txt"
        lines = {
            line.strip().split("==", 1)[0].split("~=", 1)[0].split(">=", 1)[0].lower()
            for line in requirements.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

        self.assertNotIn("the-new-hotness", lines)
        self.assertNotIn("beautifulreport", lines)
        self.assertIn("curl-cffi", lines)
        self.assertIn("pycryptodome", lines)
        self.assertIn("uvicorn", lines)
        self.assertIn("yt-dlp", lines)


if __name__ == "__main__":
    unittest.main()
