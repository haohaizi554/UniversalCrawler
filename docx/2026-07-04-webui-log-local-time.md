# WebUI 日志时间应使用本地时间

## 背景

在日志中心排查任务时，WebUI 前端自己追加的运行时日志曾出现明显时差。后端和 GUI 使用系统本地时间生成 `YYYY-MM-DD HH:MM:SS`，但 WebUI 的 `appendLog()` 使用了 `Date.prototype.toISOString()`，该方法按 UTC 输出，导致用户看到的前端运行时日志比本地时间慢 8 小时。

## 根因

`toISOString()` 永远输出 UTC 时间。它适合跨时区传输或存储标准时间戳，但不适合作为用户界面中的本地时间展示。日志中心的筛选和 GUI 展示都按本地时间语义工作，因此前端生成 UTC 字符串会和同一页面里的后端日志产生错位。

## 修复

WebUI 新增 `formatLocalDateTime()`，通过 `getFullYear()`、`getMonth()`、`getDate()`、`getHours()`、`getMinutes()`、`getSeconds()` 读取浏览器本地时间并格式化为 `YYYY-MM-DD HH:MM:SS`。`appendLog()` 改为调用该函数。

## 验证

- 静态测试确认 `appendLog()` 不再调用 `toISOString()`。
- 浏览器测试传入固定本地 `Date(2026, 6, 4, 6, 24, 9)`，输出必须为 `2026-07-04 06:24:09`。

## 经验

界面展示时间必须先明确语义：如果是“用户看到的操作时间”，优先使用本地时间；如果是跨系统传输、排序或审计存储，再使用 UTC 或带时区的时间戳。不要把 `toISOString()` 直接作为可见 UI 时间。
