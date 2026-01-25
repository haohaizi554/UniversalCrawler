# app/models.py

import time
import random
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class VideoItem:
    """
    统一视频数据模型
    用于在爬虫线程、UI主线程和下载线程之间传递数据
    """
    # 核心字段
    url: str
    title: str
    source: str         # 'missav' 或 'kuaishou'
    # 状态字段
    id: str = field(init=False)      # 唯一标识符
    status: str = "waiting"          # waiting, downloading, finished, error
    progress: int = 0
    local_path: str = ""             # 下载后的本地绝对路径
    # 元数据 (用于存储特定来源的特殊信息)
    # MissAV: 存储 header, proxy, 标签(tags), 分数(score)
    # 快手: 存储 author, 原始 headers
    meta: Dict = field(default_factory=dict)
    def __post_init__(self):
        """初始化后自动生成唯一ID"""
        # 生成规则：毫秒级时间戳 + 3位随机数，确保同一毫秒内的并发也不会重复
        self.id = f"{int(time.time() * 1000)}_{random.randint(100, 999)}"
        # 去除标题首尾空格
        if self.title:
            self.title = self.title.strip()
    def get_safe_filename(self, extension: str = ".mp4") -> str:
        # 核心修复：生成安全且唯一的文件名
        # 解决原项目中标题为空时文件覆盖的问题
        # 1. 获取基础标题
        raw_name = self.title
        # 2. 如果是 MissAV，尝试追加标签后缀 (完全复刻虾片.py的命名逻辑)
        # 例如: "ABP-123 [中文字幕]"
        if self.source == "missav":
            tags = self.meta.get("tags", [])
            suffix = ""
            if "中文字幕" in tags: suffix = " [中文字幕]"
            elif "英文字幕" in tags: suffix = " [英文字幕]"
            elif "无码流出" in tags: suffix = " [无码]"
            raw_name += suffix
        # 3. 清理非法字符 (Windows/Linux 文件名限制)
        # 替换 \ / : * ? " < > | 为下划线
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', raw_name).strip()
        # 4. 【关键修复】如果清理后标题为空，或者原始标题就是空的
        # 强制使用 "来源_ID" 作为文件名，保证绝对唯一
        if not safe_name:
            safe_name = f"{self.source}_UNKNOWN_{self.id}"
        # 5. 限制文件名长度 (防止操作系统报错)
        if len(safe_name) > 220:
            safe_name = safe_name[:220]
        # 6. 确保后缀名正确
        if not extension.startswith("."):
            extension = f".{extension}"
        return f"{safe_name}{extension}"
    def update_from_dict(self, data: dict):
        """从字典更新属性 (便于从配置或临时对象恢复)"""
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)
# ================= 辅助类 =================
class AppConfig:
    """简单的配置持有类，用于在各模块间传递用户设置"""
    def __init__(self):
        # 通用路径
        self.save_dir = ""
        # MissAV 专属配置
        self.missav_proxy = "http://127.0.0.1:7890"  # 默认代理
        self.missav_individual_only = False          # 仅单体
        self.missav_sort_priority = ["中文字幕", "英文字幕", "无码流出", "普通版"] # 排序偏好