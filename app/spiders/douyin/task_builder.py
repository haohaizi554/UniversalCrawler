"""爬虫实现模块，负责 `app/spiders/douyin/task_builder.py` 对应平台的采集、解析或任务装配逻辑。"""

from __future__ import annotations
from app.models import VideoItem
from app.spiders.base_task_builder import BaseTaskBuilder

class DouyinTaskBuilder(BaseTaskBuilder):
    """负责将解析结果转换为 `DouyinTaskBuilder` 对应的任务或数据对象。"""
    def build_items(self, item: VideoItem, trace_id_factory) -> list[VideoItem]:
        """构建 `items` 对应的结果、参数或对象，供 `DouyinTaskBuilder` 使用。"""
        # #region debug-point K:douyin-build-items-enter
        try:
            import json as _dbg_json, urllib.request as _dbg_request, time as _dbg_time; _p='.dbg/interactive-resource-crash.env'; _u='http://127.0.0.1:7777/event'; _s='interactive-resource-crash'; exec("try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept Exception: pass"); _dbg_request.urlopen(_dbg_request.Request(_u, data=_dbg_json.dumps({"sessionId":_s,"runId":"pre-fix","hypothesisId":"K","location":"app/spiders/douyin/task_builder.py:build_items","msg":"[DEBUG] douyin task builder entered","data":{"title":item.title,"is_gallery":bool(item.meta.get('is_gallery')),"content_type":item.meta.get('content_type'),"images_data_count":len(item.meta.get('images_data', []) or []),"has_url":bool(item.url),"url_head":str(item.url)[:120]},"ts":int(_dbg_time.time()*1000)}).encode(), headers={"Content-Type":"application/json"}), timeout=0.5).read()
        except Exception:
            pass
        # #endregion
        if not item.meta.get("is_gallery"):
            return [item]

        built_items: list[VideoItem] = []
        images_data = item.meta.get("images_data", [])
        base_title = item.title
        for idx, image_info in enumerate(images_data):
            image_url = image_info.get("image_url", "")
            live_url = image_info.get("live_video_url", "")
            seq = idx + 1
            base_trace = item.meta.get("trace_id", trace_id_factory("dy"))

            if live_url:
                live_item = VideoItem(url=live_url, title=f"{base_title}_{seq}", source="douyin")
                live_item.meta = item.meta.copy()
                live_item.meta.update(
                    self.build_download_meta(
                        trace_id=f"{base_trace}-live-{seq}",
                        is_gallery=False,
                        content_type="video",
                        media_label="实况",
                    )
                )
                built_items.append(live_item)
            elif image_url:
                image_item = VideoItem(url=image_url, title=f"{base_title}_{seq}", source="douyin")
                image_item.meta = item.meta.copy()
                image_item.meta.update(
                    self.build_download_meta(
                        trace_id=f"{base_trace}-img-{seq}",
                        is_gallery=False,
                        content_type="image",
                        media_label="图集",
                    )
                )
                built_items.append(image_item)
        # #region debug-point K:douyin-build-items-exit
        try:
            import json as _dbg_json, urllib.request as _dbg_request, time as _dbg_time; _p='.dbg/interactive-resource-crash.env'; _u='http://127.0.0.1:7777/event'; _s='interactive-resource-crash'; exec("try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept Exception: pass"); _dbg_request.urlopen(_dbg_request.Request(_u, data=_dbg_json.dumps({"sessionId":_s,"runId":"pre-fix","hypothesisId":"K","location":"app/spiders/douyin/task_builder.py:build_items","msg":"[DEBUG] douyin task builder built items","data":{"title":item.title,"built_count":len(built_items),"image_candidates":len(images_data or []),"sample_titles":[built.title for built in built_items[:3]]},"ts":int(_dbg_time.time()*1000)}).encode(), headers={"Content-Type":"application/json"}), timeout=0.5).read()
        except Exception:
            pass
        # #endregion
        return built_items
