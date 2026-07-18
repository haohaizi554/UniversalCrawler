"""Platform-specific copy for the interactive terminal guide."""

from __future__ import annotations

_PLATFORM_GUIDE = {
    "douyin": {
        "input_label": "主页链接、分享链接或合集链接",
        "examples": [
            "主页链接: https://www.douyin.com/user/xxx",
            "分享链接: https://v.douyin.com/xxxxx/",
            "合集链接: 带 collection / mix / modal_id 的链接",
        ],
        "limit_label": "视频数量",
        "empty_tip": "优先尝试主页链接或分享链接；纯数字 UID 当前仍不支持。",
        "result_tip": "抖音会优先按 GUI 同步流程拉起扫码、采集、选择并直接入队下载。",
    },
    "xiaohongshu": {
        "input_label": "小红书关键词、笔记链接或作者主页链接",
        "examples": [
            "关键词: 穿搭 / 探店 / 摄影",
            "笔记链接: https://www.xiaohongshu.com/explore/...",
            "作者主页: https://www.xiaohongshu.com/user/profile/...",
        ],
        "limit_label": "笔记数量",
        "empty_tip": "建议优先使用完整笔记链接或作者主页链接；关键词模式会先搜索再二次选择。",
        "result_tip": "小红书会自动准备浏览器 Cookie，会话不足时可在浏览器中手动登录后继续。",
    },
    "bilibili": {
        "input_label": "BV 号、UP 主页、合集链接或关键词",
        "examples": [
            "BV 号: BV1xx411c7mD",
            "UP 主页: https://space.bilibili.com/123456",
            "合集/视频链接: https://www.bilibili.com/video/BVxxxx",
        ],
        "limit_label": "搜索页数",
        "empty_tip": "可尝试直接输入 BV 号、UP 主页链接或合集链接，通常比模糊关键词更稳定。",
        "result_tip": "B 站会沿用 GUI 的两层选择流程：先选主项目，再按需展开分 P / 合集。",
    },
    "kuaishou": {
        "input_label": "快手主页链接、分享链接、快手号或关键词",
        "examples": [
            "主页链接: https://www.kuaishou.com/profile/xxx",
            "分享链接: https://v.kuaishou.com/xxxxx/ 或分享文案中的快手链接",
            "快手号: 直接输入纯数字快手号",
            "关键词: 先进入站内搜索，再从结果跳到主页继续扫描",
        ],
        "limit_label": "视频数量",
        "empty_tip": "快手建议优先使用主页链接或分享链接；关键词模式会先走站内搜索再进入主页。",
        "result_tip": "快手会弹浏览器并允许你在页面里手动登录；分享链接会直接解析单条作品并入队下载。",
    },
    "missav": {
        "input_label": "番号、演员名或 MissAV 链接",
        "examples": [
            "番号: SSIS-001",
            "演员名: 三上悠亚",
            "列表/详情链接: https://missav.ai/...",
        ],
        "limit_label": "筛选偏好",
        "empty_tip": "如果没有结果，先确认代理可用，再尝试直接输入番号或作品链接。",
        "result_tip": "MissAV 会先扫列表、再按 GUI 同步流程筛最佳版本并嗅探 m3u8。",
    },
}


def guide_for(platform_id: str, platform_info: dict | None = None) -> dict:
    """Return built-in guidance or a useful fallback for external plugins."""

    specific = _PLATFORM_GUIDE.get(platform_id)
    if specific is not None:
        return dict(specific)

    info = platform_info or {}
    name = str(info.get("name") or platform_id)
    placeholder = str(info.get("search_placeholder") or "输入关键词或链接")
    return {
        "input_label": placeholder,
        "examples": [],
        "limit_label": "资源数量",
        "empty_tip": "请检查输入、登录状态和插件配置。",
        "result_tip": f"{name} 将使用插件提供的默认配置执行搜索与下载。",
    }
