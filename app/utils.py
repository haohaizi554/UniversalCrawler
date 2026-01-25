# app/utils.py

import os
import json
import re
import shutil
from datetime import time
from PyQt6.QtCore import QByteArray

class ConfigManager:
    def __init__(self, filename="config.json"):
        self.filename = filename
        self.data = self._load_defaults()
        self._load_from_disk()
    def _load_defaults(self):
        return {
            "common": {
                "save_directory": os.path.join(os.getcwd(), "Downloads"),
                "last_source": "kuaishou",
                "theme": "dark"
            },
            "missav": {
                "proxy_app": "Clash (7890)",
                "proxy_url": "http://127.0.0.1:7890",
                "priority": "中文字幕优先",
                "individual_only": False
            },
            "bilibili": {
                "auth_file": "bili_auth.json",  # 自动保存的 Cookie 文件
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            "ui": {
                "geometry": "",
                "window_state": "",
                "splitter_state": "",
                "main_splitter_state": "",
                "right_splitter_state": "",
                "is_fullscreen_mode": False
            }
        }
    def _load_from_disk(self):
        if not os.path.exists(self.filename):
            self.save()
            return
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
                self._recursive_update(self.data, saved_data)
        except Exception as e:
            print(f"⚠️ 配置文件损坏或不兼容: {e}")
            self._reset_config()
    def _reset_config(self):
        """备份坏文件并重置"""
        if os.path.exists(self.filename):
            backup_name = f"{self.filename}.bak.{int(time.time())}"
            try:
                shutil.move(self.filename, backup_name)
                print(f"✅ 已将损坏的配置备份为: {backup_name}")
            except: pass
        self.data = self._load_defaults()
        self.save()
    def _recursive_update(self, target, source):
        for k, v in source.items():
            if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                self._recursive_update(target[k], v)
            else:
                # 类型检查：如果保存的类型和默认类型不一致（除了None），则忽略，防止注入坏数据
                default_type = type(target.get(k))
                if target.get(k) is not None and v is not None and not isinstance(v, default_type):
                    continue
                target[k] = v
    def save(self):
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"❌ 保存配置失败: {e}")
    # --- 通用 Get/Set ---
    def get(self, section, key, default=None):
        try:
            val = self.data.get(section, {}).get(key)
            return val if val is not None else default
        except:
            return default
    def set(self, section, key, value):
        if section not in self.data: self.data[section] = {}
        self.data[section][key] = value
        self.save()
    # --- UI 状态专用 ---
    def save_ui_state(self, geometry: QByteArray, state: QByteArray,
                      main_splitter: QByteArray, right_splitter: QByteArray,
                      is_fs: bool):
        self.data["ui"]["geometry"] = geometry.toHex().data().decode()
        self.data["ui"]["window_state"] = state.toHex().data().decode()
        self.data["ui"]["main_splitter_state"] = main_splitter.toHex().data().decode()
        self.data["ui"]["right_splitter_state"] = right_splitter.toHex().data().decode()
        self.data["ui"]["is_fullscreen_mode"] = is_fs
        self.save()
    def update_missav_proxy(self, app_name, url):
        self.data["missav"]["proxy_app"] = app_name
        self.data["missav"]["proxy_url"] = url
        self.save()
def format_size(size_bytes):
    if size_bytes == 0: return "0 B"
    import math
    if size_bytes < 0: return "Unknown"
    i = int(math.log(size_bytes, 1024))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {('B','KB','MB','GB')[i]}"
def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]', '_', str(name)).strip()[:200]
cfg = ConfigManager()