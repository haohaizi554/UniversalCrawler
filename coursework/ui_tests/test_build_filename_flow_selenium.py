"""Selenium scenario 2: build media filename flow."""

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


CASES = [
    {
        "title": "CAWD-377",
        "source": "missav",
        "extension": "mp4",
        "tags": "中文字幕",
        "expected": "CAWD-377 [中文字幕].mp4",
    },
    {
        "title": "demo",
        "source": "bilibili",
        "extension": "m4a",
        "tags": "",
        "expected": "demo.m4a",
    },
]


def run() -> int:
    """执行当前对象或脚本的主流程。"""
    driver = create_driver()
    wait = WebDriverWait(driver, 10)
    try:
        for case in CASES:
            driver.get("http://127.0.0.1:8765/")
            wait.until(EC.element_to_be_clickable((By.ID, "nav-build"))).click()
            wait.until(EC.visibility_of_element_located((By.ID, "build-scene-title")))
            for element_id, value in [
                ("title-input", case["title"]),
                ("source-input", case["source"]),
                ("extension-input", case["extension"]),
                ("tags-input", case["tags"]),
            ]:
                field = driver.find_element(By.ID, element_id)
                field.clear()
                field.send_keys(value)
            driver.find_element(By.XPATH, "//button[@id='build-btn']").click()
            result = wait.until(EC.visibility_of_element_located((By.ID, "filename-result"))).text
            assert result == case["expected"], f"expected {case['expected']}, got {result}"
        print("build filename selenium flow passed")
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(run())
