"""Static toolbox catalog and snapshot helpers."""

from __future__ import annotations

from shared.icon_contract import tool_icon_file


TOOLBOX_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "id": "link_parser",
        "title": "链接解析",
        "summary": "解析网页或文本中的链接，提取视频、图片等资源地址",
        "input_example": "https://www.douyin.com/user/MS4wLjABAAAA...",
        "output_example": "解析出视频、图片、作者主页等可下载资源地址",
        "icon": "link",
    },
    {
        "id": "batch_rename",
        "title": "批量重命名",
        "summary": "按规则、序号和预览结果批量重命名本地文件",
        "input_example": "D:\\Videos\\*.mp4 + {platform}_{title}_{index}",
        "output_example": "生成可预览、可回滚的批量重命名方案",
        "icon": "rename",
    },
    {
        "id": "cover_extract",
        "title": "封面提取",
        "summary": "从视频文件中提取封面图片，支持单个或批量提取",
        "input_example": "选择本地视频文件或下载完成列表",
        "output_example": "导出 JPG/PNG 封面图并写入文件信息",
        "icon": "image",
    },
    {
        "id": "video_to_audio",
        "title": "视频转音频",
        "summary": "将视频文件转换为音频，支持多种格式和质量设置",
        "input_example": "MP4/MKV/WebM 视频文件",
        "output_example": "输出 MP3/AAC/WAV 音频文件",
        "icon": "music",
    },
    {
        "id": "dedupe_scan",
        "title": "本地去重扫描",
        "summary": "扫描并查找重复文件，支持按内容或文件名去重",
        "input_example": "选择下载目录或任意本地目录",
        "output_example": "生成重复文件分组和可清理建议",
        "icon": "search",
    },
    {
        "id": "metadata_viewer",
        "title": "元数据查看",
        "summary": "查看视频、音频和图片文件的详细元数据",
        "input_example": "本地视频、音频、图片文件",
        "output_example": "展示编码、分辨率、时长、码率和容器信息",
        "icon": "metadata",
    },
    {
        "id": "format_convert",
        "title": "格式转换",
        "summary": "转换视频、音频和图片文件格式",
        "input_example": "选择源文件和目标格式",
        "output_example": "输出转换后的媒体文件并保留来源记录",
        "icon": "convert",
    },
    {
        "id": "file_verify",
        "title": "文件校验",
        "summary": "计算并校验文件哈希值，支持 MD5、SHA1、SHA256",
        "input_example": "选择一个或多个本地文件",
        "output_example": "输出 MD5、SHA1、SHA256 校验值",
        "icon": "shield",
    },
)


def toolbox_items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in TOOLBOX_DEFINITIONS:
        entry = dict(item)
        entry["icon_file"] = tool_icon_file(entry.get("icon", ""))
        items.append(entry)
    return items


def toolbox_recent_items() -> list[dict[str, str]]:
    return [
        {"id": "link_parser", "title": "链接解析", "last_used": "今天 18:24"},
        {"id": "video_to_audio", "title": "视频转音频", "last_used": "今天 17:35"},
        {"id": "metadata_viewer", "title": "元数据查看", "last_used": "今天 14:10"},
    ]


def valid_tool_ids() -> set[str]:
    return {item["id"] for item in TOOLBOX_DEFINITIONS}
