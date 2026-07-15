"""把抖音与 TikTok 原始响应转换为统一的数据记录。"""

from datetime import datetime
from json import dumps
from time import localtime, strftime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from urllib.parse import urlparse

# 最小依赖环境下使用索引占位值，保证提取器可被导入并显式暴露缺失字段。
try:
    from ..tools import (
        AUTHOR_COVER_INDEX,
        AUTHOR_COVER_URL_INDEX,
        AVATAR_LARGER_INDEX,
        BITRATE_INFO_TIKTOK_INDEX,
        COMMENT_IMAGE_INDEX,
        COMMENT_IMAGE_LIST_INDEX,
        COMMENT_STICKER_INDEX,
        DYNAMIC_COVER_INDEX,
        HOT_WORD_COVER_INDEX,
        IMAGE_INDEX,
        IMAGE_TIKTOK_INDEX,
        LIVE_COVER_INDEX,
        LIVE_DATA_INDEX,
        MUSIC_COLLECTION_COVER_INDEX,
        MUSIC_COLLECTION_DOWNLOAD_INDEX,
        MUSIC_INDEX,
        SEARCH_AVATAR_INDEX,
        SEARCH_USER_INDEX,
        STATIC_COVER_INDEX,
        VIDEO_INDEX,
        VIDEO_TIKTOK_INDEX,
        DownloaderError,
    )
except ImportError:
    VIDEO_INDEX = -1
    VIDEO_TIKTOK_INDEX = 0
    IMAGE_INDEX = -1
    IMAGE_TIKTOK_INDEX = -1

    class DownloaderError(Exception):

        pass

# 尚未接入外部筛选器时不过滤作品，保持现有数据流。
def condition_filter(data: dict) -> bool:
    """默认不过滤任何作品，供上层按需覆写筛选条件。"""
    return True

try:
    from ..translation import _
except ImportError:
    # 独立导入时保留原文，避免翻译层缺失阻断提取流程。
    def _(x):
        return x

if TYPE_CHECKING:
    from datetime import date
    from typing import Any
    Parameter = Any

__all__ = ["Extractor"]

class Extractor:
    """把抖音或 TikTok 原始响应清洗成统一的数据记录结构。"""
    statistics_keys = (
        "digg_count",
        "comment_count",
        "collect_count",
        "share_count",
        "play_count",
    )
    statistics_keys_tiktok = (
        "diggCount",
        "commentCount",
        "collectCount",
        "shareCount",
        "playCount",
    )
    detail_necessary_keys = "id"
    comment_necessary_keys = "cid"
    user_necessary_keys = "sec_uid"
    extract_params_tiktok = {
        "sec_uid": "author.secUid",
        "mix_id": "playlistId",
        "uid": "author.id",
        "nickname": "author.nickname",
        "mix_title": "playlistId",  # TikTok 不返回合辑标题
    }
    extract_params = {
        "sec_uid": "author.sec_uid",
        "mix_id": "mix_info.mix_id",
        "uid": "author.uid",
        "nickname": "author.nickname",
        "mix_title": "mix_info.mix_name",
    }

    def __init__(self, params: "Parameter"):
        """缓存日志、时间格式和清洗工具，并注册不同提取模式。"""
        self.log = params.logger
        self.date_format = params.date_format
        self.cleaner = params.CLEANER
        self.type = {
            "batch": self.__batch,
            "detail": self.__detail,
            "comment": self.__comment,
            "live": self.__live,
            "user": self.__user,
            "search": self.__search,
            "hot": self.__hot,
            "music": self.__music,
        }

    def get_user_info(self, data: dict) -> dict:
        """从抖音账号字段中提取作者昵称、UID 与 sec_uid。"""
        try:
            return {
                "nickname": data["nickname"],
                "sec_uid": data["sec_uid"],
                "uid": data["uid"],
            }
        except (KeyError, TypeError):
            self.log.error(_("提取账号信息失败: {data}").format(data=data))
            return {}

    def get_user_info_tiktok(self, data: dict) -> dict:
        """从 TikTok 账号字段中提取作者昵称、UID 与 sec_uid。"""
        try:
            return {
                "nickname": data["user"]["nickname"],
                "sec_uid": data["user"]["secUid"],
                "uid": data["user"]["id"],
            }
        except (KeyError, TypeError):
            self.log.error(_("提取账号信息失败: {data}").format(data=data))
            return {}

    @staticmethod
    def generate_data_object(
        data: dict | list,
    ) -> SimpleNamespace | list[SimpleNamespace]:
        """递归把字典和列表包装成属性可点取的对象。"""
        def depth_conversion(element):
            """递归转换嵌套结构，便于后续统一使用点号访问字段。"""
            if isinstance(element, dict):
                return SimpleNamespace(
                    **{k: depth_conversion(v) for k, v in element.items()}
                )
            elif isinstance(element, list):
                return [depth_conversion(item) for item in element]
            else:
                return element

        return depth_conversion(data)

    @staticmethod
    def safe_extract(
        data: SimpleNamespace | list[SimpleNamespace],
        attribute_chain: str,
        default: str | int | list | dict | SimpleNamespace = "",
    ):
        """按 `a.b[0].c` 形式安全读取嵌套字段，失败时返回默认值。"""
        attributes = attribute_chain.split(".")
        for attribute in attributes:
            if "[" in attribute:
                parts = attribute.split("[", 1)
                attribute = parts[0]
                index = parts[1].split("]", 1)[0]
                try:
                    index = int(index)
                    data = getattr(data, attribute, None)[index]
                except (IndexError, TypeError, ValueError):
                    return default
            else:
                data = getattr(data, attribute, None)
                if not data:
                    return default
        return data or default

    async def run(
        self,
        data: list[dict],
        recorder,
        type_="detail",
        tiktok=False,
        **kwargs,
    ) -> list[dict]:
        """``type_`` 必须命中 ``self.type`` 分发表；未知键抛出 ``DownloaderError``。

        命中后的处理器统一接收 ``data, recorder, tiktok, **kwargs``。
        """
        if type_ not in self.type.keys():
            raise DownloaderError
        return await self.type[type_](data, recorder, tiktok, **kwargs)

    async def __batch(
        self,
        data: list[dict],
        recorder,
        tiktok: bool,
        name: str,
        mark: str,
        earliest,
        latest,
        same=True,
    ) -> list[dict]:
        """批量提取作品数据，并在写盘后继续执行时间与条件筛选。"""
        container = SimpleNamespace(
            all_data=[],
            template={
                "collection_time": datetime.now().strftime(self.date_format),
            },
            cache=None,
            name=name,
            mark=mark,
            same=same,  # 是否相同作者
            earliest=earliest,
            latest=latest,
        )
        # 先按平台把原始响应转成统一结构，再做去脏、记录和过滤。
        self.__platform_classify_detail(
            data,
            container,
            tiktok,
        )
        container.all_data = self.__clean_extract_data(
            container.all_data,
            self.detail_necessary_keys,
        )
        self.__extract_item_records(container.all_data)
        await self.__record_data(recorder, container.all_data)
        self.__date_filter(container)
        self.__condition_filter(container)
        self.__summary_detail(container.all_data)
        return container.all_data

    @staticmethod
    def __condition_filter(
        container: SimpleNamespace,
    ):
        """仅保留通过 condition_filter 的作品。"""
        result = [i for i in container.all_data if condition_filter(i)]
        container.all_data = result

    def __summary_detail(
        self,
        data: list[dict],
    ):
        """记录筛选完成后的作品数量。"""
        self.log.info(_("筛选处理后作品数量: {count}").format(count=len(data)))

    def __extract_batch(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ) -> None:
        """把一条抖音作品响应展开为统一记录。"""
        container.cache = container.template.copy()
        self.__extract_detail_info(container.cache, data)
        self.__extract_account_info(container, data)
        self.__extract_music(container.cache, data)
        self.__extract_statistics(container.cache, data)
        self.__extract_tags(container.cache, data)
        self.__extract_extra_info(container.cache, data)
        self.__extract_additional_info(container.cache, data)
        container.all_data.append(container.cache)

    def __extract_batch_tiktok(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ) -> None:
        """把一条 TikTok 作品响应映射为统一记录。"""
        container.cache = container.template.copy()
        self.__extract_detail_info_tiktok(container.cache, data)
        self.__extract_account_info_tiktok(container, data)
        self.__extract_music(container.cache, data, True)
        self.__extract_statistics_tiktok(container.cache, data)
        self.__extract_tags_tiktok(container.cache, data)
        self.__extract_extra_info_tiktok(container.cache, data)
        self.__extract_additional_info(container.cache, data, True)
        container.all_data.append(container.cache)

    def __extract_extra_info(
        self,
        item: dict,
        data: SimpleNamespace,
    ):
        """把锚点等额外信息序列化为文本，方便后续落库或排错。"""
        if e := self.safe_extract(data, "anchor_info"):
            extra = dumps(e, ensure_ascii=False, indent=2, default=lambda x: vars(x))
        else:
            extra = ""
        item["extra"] = extra

    def __extract_extra_info_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
    ):
        """为 TikTok 额外字段预留出口，当前先写入空值保持结构一致。"""
        item["extra"] = ""

    def __extract_commodity_data(
        self,
        item: dict,
        data: SimpleNamespace,
    ):
        """预留商品挂载信息提取入口，当前版本暂未实现。"""
        pass

    def __extract_game_data(
        self,
        item: dict,
        data: SimpleNamespace,
    ):
        """预留游戏挂载信息提取入口，当前版本暂未实现。"""
        pass

    def __extract_description(self, data: SimpleNamespace) -> str:
        """读取作品描述；缺失时由调用方回退到作品 ID。"""
        return self.safe_extract(data, "desc")

    def __clean_description(self, desc: str) -> str:
        """清理描述中的多余空白和不需要的格式噪声。"""
        return self.cleaner.clear_spaces(self.cleaner.filter(desc))

    def __format_date(
        self,
        data: int,
    ) -> str:
        """把时间戳按当前配置格式转换成可读时间字符串。"""
        return strftime(
            self.date_format,
            localtime(data or None),
        )

    def __extract_detail_info(
        self,
        item: dict,
        data: SimpleNamespace,
    ) -> None:
        """提取抖音作品的基础信息，并进一步识别视频或图集类型。"""
        item["id"] = self.safe_extract(data, "aweme_id")
        item["desc"] = (
            self.__clean_description(
                self.__extract_description(data),
            )
            or item["id"]
        )
        item["create_timestamp"] = self.safe_extract(data, "create_time")
        item["create_time"] = self.__format_date(item["create_timestamp"])
        self.__extract_text_extra(item, data)
        self.__classifying_detail(item, data)

    def __extract_detail_info_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
    ) -> None:
        """提取 TikTok 作品的基础信息，并进一步识别媒体类型。"""
        item["id"] = self.safe_extract(data, "id")
        item["desc"] = (
            self.__clean_description(self.__extract_description(data)) or item["id"]
        )
        item["create_timestamp"] = self.safe_extract(
            data,
            "createTime",
        )
        item["create_time"] = self.__format_date(item["create_timestamp"])
        self.__extract_text_extra_tiktok(item, data)
        self.__classifying_detail_tiktok(item, data)

    def __classifying_detail(
        self,
        item: dict,
        data: SimpleNamespace,
    ) -> None:
        """判断抖音作品是视频、图集还是实况，并进入对应提取分支。"""
        if images := self.safe_extract(data, "images"):
            self.__extract_image_info(item, data, images)
        else:
            self.__extract_video_info(
                item,
                data,
                _("视频"),
            )

    def __classifying_detail_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
    ) -> None:
        """判断 TikTok 作品是视频还是图集，并提取对应下载地址。"""
        if images := self.safe_extract(data, "imagePost.images"):
            self.__extract_image_info_tiktok(item, data, images)
        else:
            self.__extract_video_info_tiktok(
                item,
                data,
                _("视频"),
            )

    def __extract_additional_info(
        self,
        item: dict,
        data: SimpleNamespace,
        tiktok=False,
    ):
        """补充分享链接等衍生字段，方便后续导出和回查来源。"""
        item["share_url"] = self.__generate_link(
            item["type"],
            item["id"],
            item["unique_id"] if tiktok else None,
        )

    @staticmethod
    def __generate_link(
        type_: str,
        id_: str,
        unique_id: str = None,
    ) -> str:
        """根据平台、作品类型和 ID 生成可直接访问的分享链接。"""
        match bool(unique_id), type_:
            case True, "视频":
                return f"https://www.tiktok.com/@{unique_id}/video/{id_}"
            case True, "图集":
                return f"https://www.tiktok.com/@{unique_id}/photo/{id_}"
            case False, "视频":
                return f"https://www.douyin.com/video/{id_}"
            case False, "图集" | "实况":
                return f"https://www.douyin.com/note/{id_}"
            case _:
                return ""

    @staticmethod
    def __clean_share_url(url: str) -> str:
        """清理分享链接中的查询参数，只保留稳定的基础路径。"""
        if not url:
            return url
        parsed_url = urlparse(url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

    def __extract_image_info(
        self,
        item: dict,
        data: SimpleNamespace,
        images: list[SimpleNamespace],
    ) -> None:
        """提取抖音图集或实况作品的封面和下载地址。"""
        if any(
            self.safe_extract(
                i,
                "video",
            )
            for i in images
        ):
            self.__set_blank_data(
                item,
                data,
                _("实况"),
            )
            item["downloads"] = [
                self.__classify_slides_item(
                    i,
                )
                for i in images
            ]
        else:
            self.__set_blank_data(
                item,
                data,
                _("图集"),
            )
            item["downloads"] = [
                self.safe_extract(
                    i,
                    f"url_list[{IMAGE_INDEX}]",
                )
                for i in images
            ]

    def __extract_image_info_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
        images: list,
    ) -> None:
        """提取 TikTok 图集作品的下载地址列表。"""
        self.__set_blank_data(
            item,
            data,
            _("图集"),
        )
        item["downloads"] = [
            self.safe_extract(
                i,
                f"imageURL.urlList[{IMAGE_TIKTOK_INDEX}]",
            )
            for i in images
        ]

    def __set_blank_data(
        self,
        item: dict,
        data: SimpleNamespace,
        type_=_("图集"),
    ):
        """为图集或实况类作品补齐视频专属字段的默认值。"""
        item["type"] = type_
        item["duration"] = "00:00:00"
        item["uri"] = ""
        item["height"] = -1
        item["width"] = -1
        self.__extract_cover(item, data)

    def __extract_video_info(
        self,
        item: dict,
        data: SimpleNamespace,
        type_=_("视频"),
    ) -> None:
        """提取视频类作品的分辨率、时长、下载地址和封面。"""
        item["type"] = type_
        item["height"], item["width"], item["downloads"] = (
            self.__extract_video_download(
                data,
            )
        )
        item["duration"] = self.time_conversion(
            self.safe_extract(data, "video.duration", 0)
        )
        item["uri"] = self.safe_extract(data, "video.play_addr.uri")
        self.__extract_cover(item, data, True)

    def __classify_slides_item(
        self,
        item: SimpleNamespace,
    ) -> str:
        """识别图集单页是图片还是实况视频，并返回对应下载地址。"""
        if self.safe_extract(item, "video"):
            return self.__extract_video_download(
                item,
            )[-1]
        return self.safe_extract(item, f"url_list[{IMAGE_INDEX}]")

    def __extract_video_download(
        self,
        data: SimpleNamespace,
    ) -> tuple[int, int, str]:
        """从多组码率中挑选质量最高的一条下载地址。"""
        bit_rate: list[SimpleNamespace] = self.safe_extract(
            data,
            "video.bit_rate",
            [],
        )
        try:
            bit_rate: list[tuple[int, int, int, int, int, list[str]]] = [
                (
                    i.FPS,
                    i.bit_rate,
                    i.play_addr.data_size,
                    i.play_addr.height,
                    i.play_addr.width,
                    i.play_addr.url_list,
                )
                for i in bit_rate
            ]
            # 先按分辨率，再按帧率、码率和体积排序，最后取综合质量最高的一组。
            bit_rate.sort(
                key=lambda x: (
                    max(
                        x[3],
                        x[4],
                    ),
                    x[0],
                    x[1],
                    x[2],
                ),
            )
            return (
                (
                    bit_rate[-1][-3],
                    bit_rate[-1][-2],
                    bit_rate[-1][-1][VIDEO_INDEX],
                )
                if bit_rate
                else (-1, -1, "")
            )
        except AttributeError:
            self.log.error(
                f"视频下载地址解析失败: {data}",
                False,
            )
            height = self.safe_extract(
                bit_rate[0],
                "play_addr.height",
                -1,
            )
            width = self.safe_extract(
                bit_rate[0],
                "play_addr.width",
                -1,
            )
            url = self.safe_extract(
                bit_rate[0],
                f"play_addr.url_list[{VIDEO_INDEX}]",
            )
            return height, width, url

    def __extract_video_info_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
        type_=_("视频"),
    ) -> None:
        """提取 TikTok 视频的分辨率、时长、下载地址和封面。"""
        item["type"] = type_
        item["height"], item["width"], item["downloads"] = (
            self.__extract_video_download_tiktok(
                data,
            )
        )
        item["duration"] = self.time_conversion_tiktok(
            self.safe_extract(
                data,
                "video.duration",
                0,
            )
        )
        item["uri"] = self.safe_extract(
            data,
            f"video.bitrateInfo[{BITRATE_INFO_TIKTOK_INDEX}].PlayAddr.Uri",
        )
        self.__extract_cover_tiktok(item, data, True)

    def __extract_video_download_tiktok(
        self,
        data: SimpleNamespace,
    ) -> tuple[int, int, str]:
        """从 TikTok 码率列表中选择综合质量最高的下载地址。"""
        bitrate_info: list[SimpleNamespace] = self.safe_extract(
            data,
            "video.bitrateInfo",
            [],
        )
        try:
            bitrate_info: list[tuple[int, str, int, int, list[str]]] = [
                (
                    i.Bitrate,
                    i.PlayAddr.DataSize,
                    i.PlayAddr.Height,
                    i.PlayAddr.Width,
                    i.PlayAddr.UrlList,
                )
                for i in bitrate_info
            ]
            # 先比较分辨率，再比较码率和体积，避免仅按文件大小误选低清版本。
            bitrate_info.sort(
                key=lambda x: (
                    max(
                        x[2],
                        x[3],
                    ),
                    x[0],
                    x[1],
                ),
            )
            return (
                (
                    bitrate_info[-1][-3],
                    bitrate_info[-1][-2],
                    bitrate_info[-1][-1][VIDEO_TIKTOK_INDEX],
                )
                if bitrate_info
                else (-1, -1, "")
            )
        except AttributeError:
            self.log.error(
                f"视频下载地址解析失败: {data}",
                False,
            )
            height = self.safe_extract(
                bitrate_info[0],
                "PlayAddr.Height",
                -1,
            )
            width = self.safe_extract(
                bitrate_info[0],
                "PlayAddr.Width",
                -1,
            )
            url = self.safe_extract(
                bitrate_info[0],
                f"PlayAddr.UrlList[{VIDEO_TIKTOK_INDEX}]",
            )
            return height, width, url

    @staticmethod
    def time_conversion(time_: int) -> str:
        
        second = time_ // 1000
        return f"{second // 3600:0>2d}:{second % 3600 // 60:0>2d}:{second % 3600 % 60:0>2d}"

    @staticmethod
    def time_conversion_tiktok(seconds: int) -> str:
        
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return "{:02d}:{:02d}:{:02d}".format(int(hours), int(minutes), int(seconds))

    def __extract_text_extra(
        self,
        item: dict,
        data: SimpleNamespace,
    ):
        """提取抖音作品描述中关联的话题名称。"""
        text = [
            self.safe_extract(i, "hashtag_name")
            for i in self.safe_extract(data, "text_extra", [])
        ]
        item["text_extra"] = [i for i in text if i]

    def __extract_text_extra_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
    ):
        """提取 TikTok 作品描述中关联的话题名称。"""
        text = [
            self.safe_extract(i, "hashtagName")
            for i in self.safe_extract(data, "textExtra", [])
        ]
        item["text_extra"] = [i for i in text if i]

    def __extract_cover(
        self,
        item: dict,
        data: SimpleNamespace,
        has=False,
    ) -> None:
        """提取抖音视频封面；非视频记录统一写入空值。"""
        if has:
            item["dynamic_cover"] = self.safe_extract(
                data, f"video.dynamic_cover.url_list[{DYNAMIC_COVER_INDEX}]"
            )
            item["static_cover"] = self.safe_extract(
                data, f"video.cover.url_list[{STATIC_COVER_INDEX}]"
            )
        else:
            item["dynamic_cover"], item["static_cover"] = "", ""

    def __extract_cover_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
        has=False,
    ) -> None:
        """提取 TikTok 视频封面；非视频记录统一写入空值。"""
        if has:
            item["dynamic_cover"] = self.safe_extract(data, "video.dynamicCover")
            item["static_cover"] = self.safe_extract(data, "video.cover")
        else:
            item["dynamic_cover"], item["static_cover"] = "", ""

    def __extract_music(
        self,
        item: dict,
        data: SimpleNamespace,
        tiktok=False,
    ) -> None:
        """按平台字段提取配乐作者、标题和下载地址。"""
        if music_data := self.safe_extract(data, "music"):
            if tiktok:
                author = self.safe_extract(music_data, "authorName")
                title = self.safe_extract(music_data, "title")
                url = self.safe_extract(music_data, "playUrl")
            else:
                author = self.safe_extract(music_data, "author")
                title = self.safe_extract(music_data, "title")
                url = self.safe_extract(
                    music_data,
                    f"play_url.url_list[{MUSIC_INDEX}]",
                )

        else:
            author, title, url = "", "", ""
        item["music_author"] = author
        item["music_title"] = title
        item["music_url"] = url

    def __extract_statistics(self, item: dict, data: SimpleNamespace) -> None:
        """提取抖音互动统计，缺失字段以 -1 标记。"""
        data = self.safe_extract(data, "statistics")
        for i in self.statistics_keys:
            item[i] = self.safe_extract(
                data,
                i,
                -1,
            )

    def __extract_statistics_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
    ) -> None:
        """把 TikTok 驼峰统计字段映射到统一键名。"""
        data = self.safe_extract(data, "stats")
        for i, j in enumerate(self.statistics_keys_tiktok):
            item[self.statistics_keys[i]] = self.safe_extract(
                data,
                j,
                -1,
            )

    def __extract_tags(
        self,
        item: dict,
        data: SimpleNamespace,
    ) -> None:
        """提取抖音视频标签；接口无标签时写入空列表。"""
        if not (t := self.safe_extract(data, "video_tag")):
            item["tag"] = []
        else:
            item["tag"] = [self.safe_extract(i, "tag_name") for i in t]

    def __extract_tags_tiktok(
        self,
        item: dict,
        data: SimpleNamespace,
    ) -> None:
        """提取 TikTok 话题标签；接口无标签时写入空列表。"""
        if not (t := self.safe_extract(data, "textExtra")):
            item["tag"] = []
        else:
            item["tag"] = [self.safe_extract(i, "hashtagName") for i in t]

    def __extract_account_info(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
        key="author",
    ) -> None:
        """提取抖音作者标识、签名和展示名称。"""
        data = self.safe_extract(data, key)
        container.cache["uid"] = self.safe_extract(data, "uid")
        container.cache["sec_uid"] = self.safe_extract(data, "sec_uid")
        container.cache["unique_id"] = self.safe_extract(
            data,
            "unique_id",
        )
        container.cache["signature"] = self.safe_extract(data, "signature")
        container.cache["user_age"] = self.safe_extract(data, "user_age", -1)
        self.__extract_nickname_info(container, data)

    def __extract_account_info_tiktok(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
        key="author",
    ) -> None:
        """把 TikTok 作者字段映射到统一账号键名。"""
        data = self.safe_extract(data, key)
        container.cache["uid"] = self.safe_extract(data, "id")
        container.cache["sec_uid"] = self.safe_extract(data, "secUid")
        container.cache["unique_id"] = self.safe_extract(data, "uniqueId")
        container.cache["signature"] = self.safe_extract(data, "signature")
        container.cache["user_age"] = -1
        self.__extract_nickname_info(container, data)

    def __extract_nickname_info(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ) -> None:
        """同作者批次复用预处理名称，否则逐条清洗作者昵称。"""
        if container.same:
            container.cache["nickname"] = container.name
            container.cache["mark"] = container.mark or container.name
        else:
            name = self.cleaner.filter_name(
                self.safe_extract(data, "nickname", _("已注销账号")),
                default=_("无效账号昵称"),
            )
            container.cache["nickname"] = name
            container.cache["mark"] = name

    def preprocessing_data(
        self,
        data: list[dict] | dict,
        tiktok: bool = False,
        mode: str = ...,
        mark: str = "",
        user_id: str = "",
        mix_id: str = "",
        mix_title: str = "",
        collect_id: str = "",
        collect_name: str = "",
    ) -> tuple[
        str,
        str,
        str,
    ]:
        """校验账号或合集归属，并生成后续存储使用的 ID、名称和标记。"""
        if isinstance(data, dict):
            info = (
                self.get_user_info_tiktok(data) if tiktok else self.get_user_info(data)
            )
            if user_id != (s := info.get("sec_uid")):
                self.log.error(
                    _("sec_user_id {user_id} 与 {s} 不一致").format(
                        user_id=user_id, s=s
                    ),
                )
                return "", "", ""
            name = self.cleaner.filter_name(
                info["nickname"],
                info["uid"],
            )
            mark = self.cleaner.filter_name(
                mark,
                name,
            )
            return (
                info["uid"],
                name,
                mark,
            )
        elif isinstance(data, list):
            match mode:
                case "post":
                    item = self.__select_item(
                        data,
                        user_id,
                        (self.extract_params_tiktok if tiktok else self.extract_params)[
                            "sec_uid"
                        ],
                    )
                    id_, name, mark = self.__extract_pretreatment_data(
                        item,
                        (self.extract_params_tiktok if tiktok else self.extract_params)[
                            "uid"
                        ],
                        (self.extract_params_tiktok if tiktok else self.extract_params)[
                            "nickname"
                        ],
                        mark,
                    )
                    return id_, name, mark
                case "mix":
                    if tiktok:
                        id_ = mix_id
                        name = self.cleaner.filter_name(
                            mix_title,
                        ).strip()
                        mark = self.cleaner.filter_name(
                            mark,
                            name,
                        ).strip()
                    else:
                        item = self.__select_item(
                            data,
                            mix_id,
                            self.extract_params["mix_id"],
                        )
                        id_, name, mark = self.__extract_pretreatment_data(
                            item,
                            self.extract_params["mix_id"],
                            self.extract_params["mix_title"],
                            mark,
                            mix_title,
                        )
                    return id_, name, mark
                case "collects":
                    collect_name = self.cleaner.filter_name(
                        collect_name,
                        collect_id,
                    )
                    return collect_id, collect_name, collect_name
                case _:
                    raise DownloaderError
        else:
            raise DownloaderError

    def __select_item(
        self,
        data: list[dict],
        id_: str,
        key: str,
    ):
        """按嵌套字段值从响应列表中定位目标记录，未命中时抛出异常。"""
        for item in data:
            item = self.generate_data_object(item)
            if id_ == self.safe_extract(item, key):
                return item
        raise DownloaderError(_("提取账号信息或合集信息失败，请向作者反馈！"))

    def __extract_pretreatment_data(
        self,
        item: SimpleNamespace,
        id_: str,
        name: str,
        mark: str,
        title: str = None,  # TikTok 合辑需要直接传入标题
    ):
        """从目标记录提取 ID，并清洗名称与用户自定义标记。"""
        id_ = self.safe_extract(item, id_)
        name = self.cleaner.filter_name(
            title
            or self.safe_extract(
                item,
                name,
                id_,
            ),
        )
        mark = self.cleaner.filter_name(
            mark,
            name,
        )
        return id_, name.strip(), mark.strip()

    def __platform_classify_detail(
        self,
        data: list[dict],
        container: SimpleNamespace,
        tiktok: bool,
    ) -> None:
        """按平台选择字段映射，将每条作品追加到统一容器。"""
        if tiktok:
            [
                self.__extract_batch_tiktok(
                    container,
                    self.generate_data_object(item),
                )
                for item in data
            ]
        else:
            [
                self.__extract_batch(
                    container,
                    self.generate_data_object(item),
                )
                for item in data
            ]

    async def __detail(
        self,
        data: list[dict],
        recorder,
        tiktok: bool,
    ) -> list[dict]:
        """提取作品详情、清除无 ID 记录并写入 recorder。"""
        container = SimpleNamespace(
            all_data=[],
            template={
                "collection_time": datetime.now().strftime(self.date_format),
            },
            cache=None,
            same=False,
        )
        self.__platform_classify_detail(
            data,
            container,
            tiktok,
        )
        container.all_data = self.__clean_extract_data(
            container.all_data, self.detail_necessary_keys
        )
        self.__extract_item_records(container.all_data)
        await self.__record_data(recorder, container.all_data)
        self.__condition_filter(container)
        return container.all_data

    async def __comment(
        self,
        data: list[dict],
        recorder,
        tiktok: bool,
        source=False,
    ) -> list[dict]:
        """清洗并记录评论；source=True 时直接返回上游已清洗的数据。"""
        if not any(data):
            return []
        container = SimpleNamespace(
            all_data=[],
            template={
                "collection_time": datetime.now().strftime(self.date_format),
            },
            cache=None,
            same=False,
        )
        if source:
            container.all_data = data
        else:
            [
                self.__extract_comments_data(container, self.generate_data_object(i))
                for i in data
            ]
            container.all_data = self.__clean_extract_data(
                container.all_data, self.comment_necessary_keys
            )
            await self.__record_data(recorder, container.all_data)
        return container.all_data

    def __extract_comments_data(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ):
        """提取评论文本、图片、贴纸、回复关系和作者信息。"""
        container.cache = container.template.copy()
        container.cache["create_timestamp"] = self.safe_extract(data, "create_time")
        container.cache["create_time"] = self.__format_date(
            container.cache["create_timestamp"]
        )
        container.cache["ip_label"] = self.safe_extract(data, "ip_label", "未知")
        container.cache["text"] = self.safe_extract(data, "text")
        container.cache["image"] = self.safe_extract(
            data,
            f"image_list[{COMMENT_IMAGE_LIST_INDEX}].origin_url.url_list[{COMMENT_IMAGE_INDEX}]",
        )
        container.cache["sticker"] = self.safe_extract(
            data, f"sticker.static_url.url_list[{COMMENT_STICKER_INDEX}]"
        )
        container.cache["digg_count"] = self.safe_extract(data, "digg_count", -1)
        container.cache["reply_to_reply_id"] = self.safe_extract(
            data, "reply_to_reply_id"
        )
        container.cache["reply_comment_total"] = self.safe_extract(
            data, "reply_comment_total", 0
        )
        container.cache["reply_id"] = self.safe_extract(data, "reply_id")
        container.cache["cid"] = self.safe_extract(data, "cid")
        self.__extract_account_info(container, data, "user")
        container.all_data.append(container.cache)

    @classmethod
    def extract_reply_ids(cls, data: list[dict]) -> list[str]:
        """返回存在回复的一级评论 ID，供回复接口继续分页。"""
        container = SimpleNamespace(
            reply_ids=[],
            cache=None,
        )
        for item in data:
            item = cls.generate_data_object(item)
            container.cache = {
                "reply_comment_total": cls.safe_extract(
                    item,
                    "reply_comment_total",
                    0,
                ),
                "cid": cls.safe_extract(item, "cid"),
            }
            cls.__filter_reply_ids(container)
        return container.reply_ids

    @staticmethod
    def __filter_reply_ids(container: SimpleNamespace):
        """仅收集 reply_comment_total 大于零的评论 ID。"""
        if container.cache["reply_comment_total"] > 0:
            container.reply_ids.append(container.cache["cid"])

    async def __live(
        self,
        data: list[dict],
        recorder,
        tiktok: bool,
        *args,
    ) -> list[dict]:
        """按平台字段提取直播间信息，不写入 recorder。"""
        container = SimpleNamespace(all_data=[])
        if tiktok:
            [
                self.__extract_live_data_tiktok(container, self.generate_data_object(i))
                for i in data
            ]
        else:
            [
                self.__extract_live_data(container, self.generate_data_object(i))
                for i in data
            ]
        return container.all_data

    def __extract_live_data(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ):
        """兼容直播页与分享回流两种抖音响应结构。"""
        if data := self.safe_extract(
            data, f"data.data[{LIVE_DATA_INDEX}]"
        ) or self.safe_extract(data, "data.room"):
            live_data = {
                "status": self.safe_extract(data, "status"),
                "nickname": self.safe_extract(data, "owner.nickname"),
                "title": self.safe_extract(data, "title"),
                "flv_pull_url": vars(
                    self.safe_extract(
                        data,
                        "stream_url.flv_pull_url",
                        SimpleNamespace(),
                    )
                ),
                "hls_pull_url_map": vars(
                    self.safe_extract(
                        data,
                        "stream_url.hls_pull_url_map",
                        SimpleNamespace(),
                    )
                ),
                "cover": self.safe_extract(data, f"cover.url_list[{LIVE_COVER_INDEX}]"),
                "total_user_str": self.safe_extract(data, "stats.total_user_str"),
                "user_count_str": self.safe_extract(data, "stats.user_count_str"),
            }
            container.all_data.append(live_data)

    def __extract_live_data_tiktok(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ):
        """提取 TikTok 直播状态、主播信息和拉流地址。"""
        data = self.safe_extract(data, "data")
        live_data = {
            "create_time": datetime.fromtimestamp(t)
            if (t := self.safe_extract(data, "create_time"))
            else "未知",
            "id_str": self.safe_extract(data, "id_str"),
            "like_count": self.safe_extract(data, "like_count"),
            "nickname": self.safe_extract(data, "owner.nickname"),
            "display_id": self.safe_extract(data, "owner.display_id"),
            "title": self.safe_extract(data, "title"),
            "user_count": self.safe_extract(data, "user_count"),
            "flv_pull_url": vars(self.safe_extract(data, "stream_url.flv_pull_url")),
            "message": self.safe_extract(data, "message"),
            "prompts": self.safe_extract(data, "prompts"),
        }
        container.all_data.append(live_data)

    async def __user(
        self,
        data: list[dict],
        recorder,
        tiktok: bool,
    ) -> list[dict]:
        """提取账号资料、移除无 sec_uid 记录并写入 recorder。"""
        container = SimpleNamespace(
            all_data=[],
            cache=None,
            template={
                "collection_time": datetime.now().strftime(self.date_format),
            },
        )
        [
            self.__extract_user_data(container, self.generate_data_object(i))
            for i in data
        ]
        container.all_data = self.__clean_extract_data(
            container.all_data, self.user_necessary_keys
        )
        await self.__record_data(recorder, container.all_data)
        return container.all_data

    def __extract_user_data(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ):
        """把抖音账号资料展开为可存储的扁平记录。"""
        container.cache = container.template.copy()
        container.cache["avatar"] = self.safe_extract(
            data, f"avatar_larger.url_list[{AVATAR_LARGER_INDEX}]"
        )
        container.cache["city"] = self.safe_extract(data, "city")
        container.cache["country"] = self.safe_extract(data, "country")
        container.cache["district"] = self.safe_extract(data, "district")
        container.cache["favoriting_count"] = self.safe_extract(
            data, "favoriting_count", -1
        )
        container.cache["follower_count"] = self.safe_extract(
            data, "follower_count", -1
        )
        container.cache["max_follower_count"] = self.safe_extract(
            data, "max_follower_count", -1
        )
        container.cache["following_count"] = self.safe_extract(
            data, "following_count", -1
        )
        container.cache["total_favorited"] = self.safe_extract(
            data, "total_favorited", -1
        )
        container.cache["gender"] = {1: "男", 2: "女"}.get(
            self.safe_extract(data, "gender"),
            "未知",
        )
        container.cache["ip_location"] = self.safe_extract(data, "ip_location")
        container.cache["nickname"] = self.safe_extract(data, "nickname")
        container.cache["province"] = self.safe_extract(data, "province")
        container.cache["school_name"] = self.safe_extract(data, "school_name")
        container.cache["sec_uid"] = self.safe_extract(data, "sec_uid")
        container.cache["signature"] = self.safe_extract(data, "signature")
        container.cache["uid"] = self.safe_extract(data, "uid")
        container.cache["unique_id"] = self.safe_extract(data, "unique_id")
        container.cache["user_age"] = self.safe_extract(data, "user_age", -1)
        container.cache["cover"] = self.safe_extract(
            data, f"cover_url[{AUTHOR_COVER_URL_INDEX}].url_list[{AUTHOR_COVER_INDEX}]"
        )
        container.cache["short_id"] = self.safe_extract(data, "short_id")
        container.cache["aweme_count"] = self.safe_extract(data, "aweme_count", -1)
        container.cache["verify"] = self.safe_extract(data, "custom_verify", "无")
        container.cache["enterprise"] = self.safe_extract(
            data, "enterprise_verify_reason", "无"
        )
        container.cache["url"] = (
            f"https://www.douyin.com/user/{container.cache['sec_uid']}"
        )
        container.all_data.append(container.cache)

    async def __search(
        self,
        data: list[dict],
        recorder,
        tiktok: bool,
        tab: int,
    ) -> list[dict]:
        """按 tab 分派综合、用户或直播搜索结果。"""
        if tab in {0, 1}:
            return await self.__search_general(data, recorder)
        elif tab == 2:
            return await self.__search_user(data, recorder)
        elif tab == 3:
            return await self.__search_live(data, recorder)

    async def __search_general(
        self,
        data: list[dict],
        recorder,
    ) -> list[dict]:
        """归一化综合或视频搜索结果并写入 recorder。"""
        container = SimpleNamespace(
            all_data=[],
            cache=None,
            template={
                "collection_time": datetime.now().strftime(self.date_format),
            },
            same=False,
        )
        [
            self.__search_result_classify(container, self.generate_data_object(i))
            for i in data
        ]
        await self.__record_data(recorder, container.all_data)
        return container.all_data

    def __search_result_classify(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ):
        """识别不同搜索卡片，并将其中的作品展开为统一记录。"""
        if d := self.safe_extract(data, "aweme_info"):
            self.__extract_batch(container, d)
        elif d := self.safe_extract(data, "aweme_mix_info.mix_items"):
            [self.__extract_batch(container, i) for i in d]
        elif d := self.safe_extract(data, "card_info.attached_info.aweme_list"):
            [self.__extract_batch(container, i) for i in d]
        elif d := self.safe_extract(data, f"user_list[{SEARCH_USER_INDEX}].items"):
            [self.__extract_batch(container, i) for i in d]
        else:
            self.log.error(f"Unreported search results: {data}", False)

    async def __search_user(
        self,
        data: list[dict],
        recorder,
    ) -> list[dict]:
        """提取用户搜索结果并写入 recorder。"""
        container = SimpleNamespace(
            all_data=[],
            cache=None,
            template={
                "collection_time": datetime.now().strftime(self.date_format),
            },
        )
        [
            self.__deal_search_user_live(
                container, self.generate_data_object(i["user_info"])
            )
            for i in data
        ]
        await self.__record_data(recorder, container.all_data)
        return container.all_data

    def __deal_search_user_live(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
        user=True,
    ):
        """提取用户搜索与直播作者共用的账号字段。"""
        if user:
            container.cache = container.template.copy()
        container.cache["avatar"] = self.safe_extract(
            data,
            f"{'avatar_thumb' if user else 'avatar_larger'}.url_list[{SEARCH_AVATAR_INDEX}]",
        )
        container.cache["nickname"] = self.safe_extract(data, "nickname")
        container.cache["sec_uid"] = self.safe_extract(data, "sec_uid")
        container.cache["signature"] = self.safe_extract(data, "signature")
        container.cache["uid"] = self.safe_extract(data, "uid")
        container.cache["short_id"] = self.safe_extract(data, "short_id")
        container.cache["verify"] = self.safe_extract(data, "custom_verify", "无")
        container.cache["enterprise"] = self.safe_extract(
            data, "enterprise_verify_reason", "无"
        )
        if user:
            container.cache["follower_count"] = self.safe_extract(
                data, "follower_count", -1
            )
            container.cache["total_favorited"] = self.safe_extract(
                data, "total_favorited", -1
            )
            container.cache["unique_id"] = self.safe_extract(data, "unique_id")
            container.all_data.append(container.cache)

    async def __search_live(
        self,
        data: list[dict],
        recorder,
    ) -> list[dict]:
        """提取直播搜索结果并写入 recorder。"""
        container = SimpleNamespace(
            all_data=[],
            cache=None,
            template={
                "collection_time": datetime.now().strftime(self.date_format),
            },
        )
        [self.__deal_search_live(container, self.generate_data_object(i)) for i in data]
        await self.__record_data(recorder, container.all_data)
        return container.all_data

    def __deal_search_live(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ):
        """合并直播作者字段与 room_id。"""
        container.cache = container.template.copy()
        self.__deal_search_user_live(
            container, self.safe_extract(data, "author"), False
        )
        container.cache["room_id"] = self.safe_extract(data, "aweme_id")
        container.all_data.append(container.cache)

    async def __hot(
        self,
        data: list[dict],
        recorder,
        tiktok: bool,
    ) -> list[dict]:
        """提取热榜记录并写入 recorder。"""
        all_data = []
        [self.__deal_hot_data(all_data, self.generate_data_object(i)) for i in data]
        await self.__record_data(recorder, all_data)
        return all_data

    def __deal_hot_data(self, container: list, data: SimpleNamespace):
        """将一条热榜词条展开为扁平记录。"""
        cache = {
            "position": str(self.safe_extract(data, "position", -1)),
            "sentence_id": self.safe_extract(data, "sentence_id"),
            "word": self.safe_extract(data, "word"),
            "video_count": str(self.safe_extract(data, "video_count", -1)),
            "event_time": self.__format_date(self.safe_extract(data, "event_time")),
            "view_count": str(self.safe_extract(data, "view_count", -1)),
            "hot_value": str(self.safe_extract(data, "hot_value", -1)),
            "cover": self.safe_extract(
                data, f"word_cover.url_list[{HOT_WORD_COVER_INDEX}]"
            ),
        }
        container.append(cache)

    async def __record_data(self, record, data: list[dict]):
        """按 recorder 的字段顺序持久化记录；未配置 recorder 时跳过。"""
        if record is None:
            return
        for i in data:
            await record.save(self.__extract_values(record, i))

    @staticmethod
    def __extract_values(record, data: dict) -> list:
        """按 recorder 的字段顺序投影记录值。"""
        return [data[key] for key in record.field_keys]

    @staticmethod
    def __date_filter(container: SimpleNamespace):
        """仅保留发布日期位于闭区间内的已提取作品。"""
        result = []
        for item in container.all_data:
            create_time = datetime.fromtimestamp(item["create_timestamp"]).date()
            if container.earliest <= create_time <= container.latest:
                result.append(item)
        container.all_data = result

    def source_date_filter(
        self,
        data: list[dict],
        earliest: "date",
        latest: "date",
        tiktok=False,
    ) -> list[dict]:
        if tiktok:
            return self.__source_date_filter(
                data,
                "createTime",
                earliest=earliest,
                latest=latest,
            )
        return self.__source_date_filter(
            data,
            earliest=earliest,
            latest=latest,
        )

    def __source_date_filter(
        self,
        data: list[dict],
        key: str = "create_time",
        earliest: "date" = ...,
        latest: "date" = ...,
    ) -> list[dict]:
        """按原始时间戳过滤；缺失时间戳时保留记录，避免误删未知日期数据。"""
        result = []
        for item in data:
            if not (create_time := item.get(key, 0)):
                result.append(item)
                continue
            create_time = datetime.fromtimestamp(create_time).date()
            if earliest <= create_time <= latest:
                result.append(item)
        self.__summary_detail(result)
        return result

    @classmethod
    def extract_mix_id(cls, data: dict) -> str:
        """从作品详情提取 mix_id；字段缺失时返回空串。"""
        data = cls.generate_data_object(data)
        return cls.safe_extract(data, "mix_info.mix_id")

    def __extract_item_records(self, data: list[dict]):
        """逐条记录成功提取的作品类型与 ID。"""
        for i in data:
            self.log.info(f"{i['type']} {i['id']} 数据提取成功", False)

    @classmethod
    def extract_mix_collect_info(cls, data: list[dict]) -> list[dict]:
        """提取合集名称与 mix_id。"""
        data = cls.generate_data_object(data)
        return [
            {
                "title": Extractor.safe_extract(i, "mix_name"),
                "id": Extractor.safe_extract(i, "mix_id"),
            }
            for i in data
        ]

    @classmethod
    def extract_collects_info(cls, data: list[dict]) -> list[dict]:
        """提取收藏夹名称与 collects_id。"""
        data = cls.generate_data_object(data)
        return [
            {
                "name": Extractor.safe_extract(i, "collects_name"),
                "id": Extractor.safe_extract(i, "collects_id_str"),
            }
            for i in data
        ]

    @staticmethod
    def __clean_extract_data(data: list[dict], key: str) -> list[dict]:
        """删除缺少指定必要键值的记录。"""
        return [i for i in data if i.get(key)]

    async def __music(
        self,
        data: list[dict],
        recorder,
        tiktok=False,
    ) -> list[dict]:
        """提取收藏音乐字段；该模式当前不写入 recorder。"""
        container = SimpleNamespace(
            all_data=[],
            template={
                "collection_time": datetime.now().strftime(self.date_format),
            },
            cache=None,
            same=False,
        )
        [
            self.__extract_collection_music(
                container,
                self.generate_data_object(item),
            )
            for item in data
        ]
        return container.all_data

    def __extract_collection_music(
        self,
        container: SimpleNamespace,
        data: SimpleNamespace,
    ):
        """将一条收藏音乐响应展开为统一记录。"""
        container.cache = container.template.copy()
        container.cache["id"] = self.safe_extract(data, "id_str")
        container.cache["title"] = self.safe_extract(data, "title")
        container.cache["author"] = self.safe_extract(data, "author")
        container.cache["album"] = self.safe_extract(data, "album")
        container.cache["cover"] = self.safe_extract(
            data, f"cover_hd.url_list[{MUSIC_COLLECTION_COVER_INDEX}]"
        )
        container.cache["download"] = self.safe_extract(
            data, f"play_url.url_list[{MUSIC_COLLECTION_DOWNLOAD_INDEX}]"
        )
        container.cache["duration"] = self.time_conversion(
            self.safe_extract(data, "duration", 0)
        )
        container.all_data.append(container.cache)
