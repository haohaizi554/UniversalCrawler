"""Shared helpers for coursework Selenium scripts."""

from __future__ import annotations

from selenium import webdriver
from selenium.common.exceptions import WebDriverException


def create_driver():
    """创建 `driver` 对应的对象、资源或结构。"""
    last_error = None

    edge_options = webdriver.EdgeOptions()
    edge_options.add_argument("--headless=new")
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--window-size=1440,900")
    try:
        return webdriver.Edge(options=edge_options)
    except WebDriverException as exc:
        last_error = exc

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1440,900")
    try:
        return webdriver.Chrome(options=chrome_options)
    except WebDriverException as exc:
        last_error = exc

    raise RuntimeError(f"无法创建 Selenium 浏览器驱动: {last_error}")
