"""包初始化模块，为 `app/spiders/kuaishou` 提供统一导出或包级说明。"""

from .parser import KuaishouParser
from .spider import KuaishouSpider
from .task_builder import KuaishouTaskBuilder

__all__ = ["KuaishouParser", "KuaishouSpider", "KuaishouTaskBuilder"]
