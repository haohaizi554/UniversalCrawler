# UI 自动化执行结果

## 场景一：文件名清洗

- 脚本：[test_sanitize_flow_selenium.py](file:///d:/desktop/UniversalCrawlerPro/coursework/ui_tests/test_sanitize_flow_selenium.py)
- 执行结果：脚本正常运行并输出 `sanitize selenium flow passed`
- 覆盖动作：打开首页、点击导航、输入文件名、点击按钮、读取结果、断言结果文本
- 截图证据：
  - [sanitize-flow-case-1.png](file:///d:/desktop/UniversalCrawlerPro/coursework/evidence/selenium/sanitize-flow-case-1.png)
  - [sanitize-flow-case-2.png](file:///d:/desktop/UniversalCrawlerPro/coursework/evidence/selenium/sanitize-flow-case-2.png)

## 场景二：媒体文件名生成

- 脚本：[test_build_filename_flow_selenium.py](file:///d:/desktop/UniversalCrawlerPro/coursework/ui_tests/test_build_filename_flow_selenium.py)
- 执行结果：脚本正常运行并输出 `build filename selenium flow passed`
- 覆盖动作：打开首页、跳转目标页面、填写表单、点击按钮、读取结果、断言结果文本
- 截图证据：
  - [build-filename-flow-case-1.png](file:///d:/desktop/UniversalCrawlerPro/coursework/evidence/selenium/build-filename-flow-case-1.png)
  - [build-filename-flow-case-2.png](file:///d:/desktop/UniversalCrawlerPro/coursework/evidence/selenium/build-filename-flow-case-2.png)

## 元素定位方式

- `By.ID`
- `By.CSS_SELECTOR`
- `By.XPATH`

## 说明

上述 Selenium 场景依赖课程接口适配层：

- [mock_api_server.py](file:///d:/desktop/UniversalCrawlerPro/coursework/api/mock_api_server.py)

当前脚本已在无头浏览器中自动保存截图；如老师要求人工操作截图，可再用同一页面手工补图。
