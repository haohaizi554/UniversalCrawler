import asyncio
from app.spiders.base_spider import BaseSpider
from app.core.douyin_wrapper import DouyinEngine
from app.models import VideoItem


class DouyinSpider(BaseSpider):
    def run(self):
        # 1. 初始化引擎 (传入信号以便打印日志)
        cookie = self.config.get("cookie", "")
        self.engine = DouyinEngine(self.sig_log, cookie_str=cookie, tiktok=False)

        # 2. 启动异步循环
        try:
            asyncio.run(self._async_pipeline())
        except Exception as e:
            self.log(f"❌ 发生错误: {e}")
        finally:
            self.sig_finished.emit()

    async def _async_pipeline(self):
        # 初始化参数（加密算法等）
        self.log("🔐 初始化加密算法...")
        await self.engine.init_async()

        results = []

        # 判断输入类型 (URL 还是 关键词)
        if "http" in self.keyword:
            self.log("🔗 识别为链接，正在解析...")
            results = await self.engine.get_detail_data(self.keyword)
        else:
            self.log(f"🔍 正在搜索: {self.keyword}...")
            # 注意：DouK 的 Search 返回的是原始数据，需要进一步提取
            # 这里简化处理，假设 get_search_data 已经返回了列表
            # 实际上你可能需要像 DouK 的 main_terminal 那样处理 Search 结果
            pass

        if not results:
            self.log("❌ 未找到有效视频")
            return

        # 3. 转换数据为 UCP 格式供弹窗选择
        dialog_items = []
        cached_items = {}  # 缓存 DouK 清洗后的完整数据

        for idx, item in enumerate(results):
            # item 是 DouK 清洗后的字典 (id, desc, nickname...)
            title = f"{item.get('desc', '')[:30]}... - @{item.get('nickname', '')}"
            dialog_items.append({'title': title, 'index': idx})
            cached_items[idx] = item

        # 4. 弹窗让用户选择 (UCP 独有功能)
        selected_indices = self.ask_user_selection(dialog_items)
        if not selected_indices:
            return

        # 5. 提交下载任务
        for idx in selected_indices:
            douk_data = cached_items[idx]

            # 构建 VideoItem
            # DouK 解析出的 'downloads' 可能是列表或字符串
            video_url = douk_data.get('uri')  # 或者从 downloads 解析

            # 兼容 DouK 的下载逻辑，如果它是图集，处理逻辑不同
            # 这里假设是视频

            # 关键：保留 DouK 的 Headers (Cookie/Referer/User-Agent)
            # 这些在 DouK 的 Parameter 中有，我们需要传递给 UCP 的 Downloader
            meta = {
                "cookie": self.engine.params.headers['Cookie'],
                "user_agent": self.engine.params.headers['User-Agent'],
                "referer": self.engine.params.headers.get('Referer', ''),
                # 如果是图集，可以将图片列表放入 meta
                "images": douk_data.get('images', [])
            }

            self.emit_video(
                url=video_url,  # 这是无水印真实地址
                title=douk_data.get('desc', '未命名'),
                source="douyin_api",  # 标记新来源
                meta=meta
            )
            self.log(f"✅ 已添加任务: {douk_data.get('desc')[:10]}")