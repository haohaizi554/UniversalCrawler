# Spider 模块说明

`app/spiders/` 是平台采集主线所在目录，当前分支将这里视为最值得持续补测试的区域。

## 统一分层

每个平台尽量保持以下结构：

- `spider.py`
  - 页面访问、流程控制、登录、用户选择、任务发射。
- `parser.py`
  - 解析页面或接口数据，负责清洗与归一化。
- `task_builder.py`
  - 把解析结果装配成统一下载元数据。

## 已接入平台

- `douyin/`
- `xiaohongshu/`
- `bilibili/`
- `kuaishou/`
- `missav/`

## 当前维护重点

- 让流程控制更容易测试。
- 减少 spider 直接承担过多数据拼装职责。
- 把纯解析和任务装配继续下沉到 `parser / task_builder`。

## 分支补强点

本分支新增覆盖了：

- B 站取流回退
- 小红书签名抓取与图文下载链
- 快手捕获流水线
- MissAV 列表扫描
- 多平台关键输入分流

修改任何平台主流程后，请同步检查 `tests/test_spider_helpers.py` 与对应文档。
