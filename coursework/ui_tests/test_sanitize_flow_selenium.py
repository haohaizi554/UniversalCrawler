"""Selenium scenario 1: sanitize filename flow."""

from __future__ import annotations
import sys
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from coursework.ui_tests.selenium_common import create_driver


SCREENSHOT_DIR = PROJECT_ROOT / "coursework" / "evidence" / "selenium"

CASES = [
    {"raw_name": "bad:/name?*.mp4.  ", "expected": "bad__name__.mp4"},
    {"raw_name": "   ", "expected": "untitled"},
]


def run() -> int:
    """执行当前对象或脚本的主流程。"""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    driver = create_driver()
    wait = WebDriverWait(driver, 10)
    try:
        for index, case in enumerate(CASES, start=1):
            driver.get("http://127.0.0.1:8765/")
            wait.until(EC.element_to_be_clickable((By.ID, "nav-sanitize"))).click()
            wait.until(EC.visibility_of_element_located((By.ID, "scene-title")))
            name_input = driver.find_element(By.ID, "name-input")
            name_input.clear()
            name_input.send_keys(case["raw_name"])
            driver.find_element(By.CSS_SELECTOR, "#sanitize-btn").click()
            result = wait.until(EC.visibility_of_element_located((By.ID, "sanitized-result"))).text
            assert result == case["expected"], f"expected {case['expected']}, got {result}"
            screenshot_path = SCREENSHOT_DIR / f"sanitize-flow-case-{index}.png"
            driver.save_screenshot(str(screenshot_path))
        print("sanitize selenium flow passed")
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(run())
