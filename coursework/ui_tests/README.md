# Selenium UI 脚本说明

本目录用于满足课程中“Python + Selenium 编写 UI 自动化脚本”的要求。

由于 `UniversalCrawlerPro` 主项目是 PyQt6 桌面应用，不直接提供 Web DOM，因此这里通过课程接口适配层提供两个最小化浏览器场景，底层仍然复用项目真实核心函数：

- 场景一：文件名清洗
- 场景二：媒体文件名生成

## 前置步骤

1. 启动课程接口与演示页面：

```bash
python coursework/api/mock_api_server.py
```

2. 确保本机可启动 Edge 或 Chrome 浏览器驱动

## 运行方式

```bash
python coursework/ui_tests/test_sanitize_flow_selenium.py
python coursework/ui_tests/test_build_filename_flow_selenium.py
```

## 技术点对应

- 初始化：由 `selenium_common.py` 创建 WebDriver
- 元素定位：
  - `By.ID`
  - `By.CSS_SELECTOR`
  - `By.XPATH`
- 测试步骤：打开页面、点击导航、输入数据、点击按钮、读取结果
- 断言：校验页面结果文本是否与预期一致
- 循环执行：每个脚本内部均遍历多个测试用例
