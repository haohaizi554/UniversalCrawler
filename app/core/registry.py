# app/core/registry.py

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QCheckBox, QComboBox, QLabel, QSpinBox
from app.utils import cfg
# 延迟导入或直接导入爬虫类
from app.spiders.kuaishou_spider import KuaishouSpider
from app.spiders.missav_spider import MissAVSpider
from app.spiders.bilibili_spider import BilibiliSpider

class BasePlugin:
    id = "base"
    name = "Base Plugin"
    def get_search_placeholder(self) -> str:
        return "请输入关键词..."
    def get_settings_widget(self, parent=None) -> QWidget:
        return None
    def get_spider_class(self):
        raise NotImplementedError
    def get_run_options(self, settings_widget: QWidget) -> dict:
        return {}

class KuaishouPlugin(BasePlugin):
    id = "kuaishou"
    name = "快手"
    def get_search_placeholder(self) -> str:
        return "输入快手号或关键词..."
    def get_settings_widget(self, parent=None) -> QWidget:
        return None
    def get_spider_class(self):
        return KuaishouSpider
    def get_run_options(self, settings_widget: QWidget) -> dict:
        return {}

class MissAVPlugin(BasePlugin):
    id = "missav"
    name = "MissAV"
    def get_search_placeholder(self) -> str:
        return "输入番号 (如 IPX-906) 或女优名..."
    def get_settings_widget(self, parent=None) -> QWidget:
        container = QWidget(parent)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        # 1. 仅单体
        self.chk_individual = QCheckBox("仅单体")
        self.chk_individual.setChecked(cfg.get("missav", "individual_only", False))
        layout.addWidget(self.chk_individual)
        # 2. 排序 (精简选项)
        self.combo_priority = QComboBox()
        # 只保留两个有效选项
        self.combo_priority.addItems(["中文字幕优先", "无码流出优先"])
        # 获取配置，如果配置是旧的"默认排序"，则强制转为"中文字幕优先"
        saved_priority = cfg.get("missav", "priority", "中文字幕优先")
        if saved_priority == "默认排序":
            saved_priority = "中文字幕优先"
        self.combo_priority.setCurrentText(saved_priority)
        layout.addWidget(self.combo_priority)
        # 3. 代理
        layout.addWidget(QLabel("代理:"))
        self.combo_proxy = QComboBox()
        self.combo_proxy.addItems(["Clash (7890)", "v2rayN (10809)", "自定义"])
        self.combo_proxy.setEditable(True)
        self.combo_proxy.setCurrentText(cfg.get("missav", "proxy_app", "Clash (7890)"))
        self.combo_proxy.setMinimumWidth(110)
        layout.addWidget(self.combo_proxy)
        return container
    def get_spider_class(self):
        return MissAVSpider
    def get_run_options(self, widget: QWidget) -> dict:
        if not widget:
            return {
                "individual_only": False,
                "priority": "中文字幕优先",
                "proxy": "http://127.0.0.1:7890"
            }
        # 提取数据
        is_individual = self.chk_individual.isChecked()
        priority = self.combo_priority.currentText()
        proxy_str = self.combo_proxy.currentText()
        proxy_url = "http://127.0.0.1:7890"
        if "7890" in proxy_str:
            proxy_url = "http://127.0.0.1:7890"
        elif "10809" in proxy_str:
            proxy_url = "http://127.0.0.1:10809"
        elif ":" in proxy_str:
            proxy_url = proxy_str if proxy_str.startswith("http") else f"http://{proxy_str}"
        # 保存回 config.json
        cfg.set("missav", "individual_only", is_individual)
        cfg.set("missav", "priority", priority)
        cfg.update_missav_proxy(proxy_str, proxy_url)
        return {
            "individual_only": is_individual,
            "priority": priority,
            "proxy": proxy_url
        }

class BilibiliPlugin(BasePlugin):
    id = "bilibili"
    name = "Bilibili"
    def get_search_placeholder(self) -> str:
        return "BV号（兼容合集） / UP主名或ID(默认全爬） / 关键词  / URL…… "
    def get_settings_widget(self, parent=None) -> QWidget:
        container = QWidget(parent)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(QLabel("爬取页数:"))
        self.spin_pages = QSpinBox()
        self.spin_pages.setRange(1, 500)
        self.spin_pages.setValue(1)
        self.spin_pages.setToolTip("搜索或列表扫描的最大页数")
        layout.addWidget(self.spin_pages)
        info = QLabel("🔒 自动登录 | 📺 最优画质")
        info.setStyleSheet("color: #00AEEC; font-weight: bold;")
        layout.addWidget(info)
        return container
    def get_spider_class(self):
        from app.spiders.bilibili_spider import BilibiliSpider
        return BilibiliSpider
    def get_run_options(self, widget: QWidget) -> dict:
        # 确保获取到的是当前 UI 上的值
        pages = 1
        try:
            if hasattr(self, 'spin_pages'):
                pages = self.spin_pages.value()
        except:
            pass
        return {"max_pages": pages}


class DouyinPlugin(BasePlugin):
    id = "douyin"
    name = "抖音"

    def get_search_placeholder(self) -> str:
        # 提示用户可以输入的内容类型
        return "主页链接 / 分享链接 / 作品、合集链接..."

    def get_settings_widget(self, parent=None) -> QWidget:
        container = QWidget(parent)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 搜索页数限制
        layout.addWidget(QLabel("搜索采集页数:"))
        self.spin_pages = QSpinBox()
        self.spin_pages.setRange(1, 100)  # 通常一页10-20条，100页足够了
        self.spin_pages.setValue(1)  # 默认搜索只抓1页
        self.spin_pages.setToolTip("仅对关键词搜索生效，主页/链接解析默认全量")
        layout.addWidget(self.spin_pages)

        # 提示信息
        info = QLabel("🚀 链接/主页全量抓取 | 扫码登录")
        info.setStyleSheet("color: #00AEEC; font-weight: bold;")  # 抖音红
        layout.addWidget(info)

        return container

    def get_spider_class(self):
        # 延迟导入，防止循环引用或模块未就绪
        from app.spiders.douyin_spider import DouyinSpider
        return DouyinSpider

    def get_run_options(self, widget: QWidget) -> dict:
        pages = 1
        try:
            if hasattr(self, 'spin_pages'):
                pages = self.spin_pages.value()
        except:
            pass
        return {
            "search_max_pages": pages,
            "timeout": 10
        }

class PluginRegistry:
    def __init__(self):
        self._plugins = {}
        self.register(DouyinPlugin())
        self.register(KuaishouPlugin())
        self.register(MissAVPlugin())
        self.register(BilibiliPlugin())
    def register(self, plugin: BasePlugin):
        self._plugins[plugin.id] = plugin
    def get_all_plugins(self):
        return list(self._plugins.values())
    def get_plugin(self, plugin_id) -> BasePlugin:
        return self._plugins.get(plugin_id)
registry = PluginRegistry()