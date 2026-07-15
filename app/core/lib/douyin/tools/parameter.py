"""校验抓取配置，并构造请求头、签名器、代理客户端和缓存目录。"""

from pathlib import Path
from shutil import move
from time import localtime, strftime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Type

from httpx import HTTPStatusError, RequestError, TimeoutException, get
from app.utils.runtime_paths import install_root, user_cache_root

try:
    from . import (
        BLANK_PREVIEW,
        DATA_HEADERS,
        DATA_HEADERS_TIKTOK,
        DOWNLOAD_HEADERS,
        DOWNLOAD_HEADERS_TIKTOK,
        PARAMS_HEADERS,
        PARAMS_HEADERS_TIKTOK,
        QRCODE_HEADERS,
        TIMEOUT,
        USERAGENT,
        Cleaner,
        DownloaderError,
        cookie_dict_to_str,
        create_client,
    )
except ImportError:
    # 独立加载时允许包级工具尚未完成初始化，实际使用仍由调用路径保证依赖存在。
    pass

# 安装目录可能只读，因此旧 ROOT/Cache 会在初始化时迁移到用户缓存目录。
PROJECT_ROOT = install_root()

from ..encrypt import (
    ABogus,
    MsToken,
    MsTokenTikTok,
    TtWid,
    TtWidTikTok,
    XBogus,
    XGnarly,
)

def _get_api_classes():
    """延迟导入 API 类，避免参数模块与接口模块循环依赖。"""
    try:
        from ..interface import API, APITikTok
        return API, APITikTok
    except ImportError:
        return None, None

try:
    from ..translation import _
except ImportError:
    def _(x):

        return x

if TYPE_CHECKING:
    from typing import Any
    DownloadRecorder = Any
    Cookie = Any
    ColorfulConsole = Any
    Settings = Any
    BaseLogger = Any
    LoggerManager = Any
    Extractor = Any
    API = Any
    APITikTok = Any
    FFMPEG = Any
    RecordManager = Any

__all__ = ["Parameter"]

class Parameter:
    """集中维护双平台请求参数及可动态更新的运行配置。"""

    NAME_KEYS = (
        "id",
        "desc",
        "create_time",
        "nickname",
        "uid",
        "mark",
        "type",
    )
    CLEANER = Cleaner()
    HEADERS = {"User-Agent": USERAGENT}
    NO_PROXY = {
        "http": None,
        "https": None,
    }

    def __init__(
        self,
        settings: "Settings",
        cookie_object: "Cookie",
        logger: Type[Any],
        console: "ColorfulConsole",
        cookie: dict | str,
        cookie_tiktok: dict | str,
        root: str,
        accounts_urls: list[dict],
        accounts_urls_tiktok: list[dict],
        mix_urls: list[dict],
        mix_urls_tiktok: list[dict],
        folder_name: str,
        name_format: str,
        desc_length: int,
        name_length: int,
        date_format: str,
        split: str,
        music: bool,
        folder_mode: bool,
        truncate: int,
        storage_format: str,
        dynamic_cover: bool,
        static_cover: bool,
        proxy: str | None | dict,
        proxy_tiktok: str | None | dict,
        twc_tiktok: str,
        download: bool,
        max_size: int,
        chunk: int,
        max_retry: int,
        max_pages: int,
        run_command: str,
        owner_url: dict,
        owner_url_tiktok: dict,
        live_qualities: str,
        ffmpeg: str,
        recorder: "DownloadRecorder",
        browser_info: dict,
        browser_info_tiktok: dict,
        timeout=10,
        douyin_platform=True,
        tiktok_platform=True,
        **kwargs,
    ):
        """校验持久化配置，并为启用的平台创建共享客户端。"""
        self.settings = settings
        self.cookie_object = cookie_object
        self.ROOT = PROJECT_ROOT
        self.cache = user_cache_root()
        self.logger = logger(PROJECT_ROOT, console)
        self.ab = ABogus()
        self.xb = XBogus()
        self.xg = XGnarly()
        self.console = console
        self.recorder = recorder
        self.preview = BLANK_PREVIEW
        self.ms_token = ""
        self.ms_token_tiktok = ""

        self.headers = DATA_HEADERS
        self.headers_tiktok = DATA_HEADERS_TIKTOK
        self.headers_download = DOWNLOAD_HEADERS
        self.headers_download_tiktok = DOWNLOAD_HEADERS_TIKTOK
        self.headers_params = PARAMS_HEADERS
        self.headers_params_tiktok = PARAMS_HEADERS_TIKTOK
        self.headers_qrcode = QRCODE_HEADERS

        self.owner_url_tiktok: SimpleNamespace | None = None

        self.cookie_dict, self.cookie_str = self.__check_cookie(cookie)
        self.cookie_dict_tiktok, self.cookie_str_tiktok = self.__check_cookie_tiktok(
            cookie_tiktok,
        )
        self.cookie_state: bool = self.__check_cookie_state()
        self.cookie_tiktok_state: bool = self.__check_cookie_state(True)

        self.root = self.__check_root(root)
        self.folder_name = self.__check_folder_name(folder_name)
        self.name_format = self.__check_name_format(name_format)
        self.desc_length = self.__check_desc_length(desc_length)
        self.name_length = self.__check_name_length(name_length)
        self.date_format = self.__check_date_format(date_format)
        self.split = self.__check_split(split)
        self.folder_mode = self.check_bool_false(folder_mode)
        self.music = self.check_bool_false(music)
        self.truncate = self.__check_truncate(truncate)
        self.storage_format = self.__check_storage_format(storage_format)
        self.dynamic_cover = self.check_bool_false(dynamic_cover)
        self.static_cover = self.check_bool_false(static_cover)
        self.twc_tiktok = self.check_str(twc_tiktok)
        self.download = self.check_bool_true(download)
        self.max_size = self.__check_max_size(max_size)
        self.chunk = self.__check_chunk(chunk)
        self.timeout = self.__check_timeout(timeout)
        self.max_retry = self.__check_max_retry(max_retry)
        self.max_pages = self.__check_max_pages(max_pages)
        self.run_command = self.__check_run_command(run_command)
        self.live_qualities = self.__check_live_qualities(live_qualities)
        self.douyin_platform = self.check_bool_true(
            douyin_platform,
        )
        self.tiktok_platform = self.check_bool_true(
            tiktok_platform,
        )

        self.browser_info = self.merge_browser_info(
            browser_info,
            {},
        )
        self.browser_info_tiktok = self.merge_browser_info(
            browser_info_tiktok,
            {},
        )

        self.proxy: str | None = self.__check_proxy(
            proxy,
            remark=_("抖音"),
            enable=self.douyin_platform,
        )
        self.proxy_tiktok: str | None = self.__check_proxy_tiktok(proxy_tiktok)
        self.client = (
            create_client(
                timeout=self.timeout,
                proxy=self.proxy,
            )
            if self.douyin_platform
            else None
        )
        self.client_tiktok = (
            create_client(
                timeout=self.timeout,
                proxy=self.proxy_tiktok,
            )
            if self.tiktok_platform
            else None
        )

        self.__generate_folders()

        self.__CHECK = {
            "root": self.__check_root,
            "folder_name": self.__check_folder_name,
            "name_format": self.__check_name_format,
            "desc_length": self.__check_desc_length,
            "name_length": self.__check_name_length,
            "date_format": self.__check_date_format,
            "split": self.__check_split,
            "folder_mode": self.check_bool_false,
            "music": self.check_bool_false,
            "truncate": self.__check_truncate,
            "storage_format": self.__check_storage_format,
            "dynamic_cover": self.check_bool_false,
            "static_cover": self.check_bool_false,
            "twc_tiktok": self.check_str,
            "download": self.check_bool_true,
            "max_size": self.__check_max_size,
            "chunk": self.__check_chunk,
            "timeout": self.__check_timeout,
            "max_retry": self.__check_max_retry,
            "max_pages": self.__check_max_pages,
            "run_command": self.__check_run_command,
            "live_qualities": self.__check_live_qualities,
            "douyin_platform": self.check_bool_true,
            "tiktok_platform": self.check_bool_true,
        }

    @staticmethod
    def check_bool_false(
        value: bool,
    ) -> bool:
        """仅接受布尔值，类型错误时按 False 处理。"""
        return value if isinstance(value, bool) else False

    @staticmethod
    def check_bool_true(
        value: bool,
    ) -> bool:
        """仅接受布尔值，类型错误时按 True 处理。"""
        return value if isinstance(value, bool) else True

    def __check_cookie_tiktok(
        self,
        cookie: dict | str,
    ) -> tuple[dict, str]:
        """将 TikTok Cookie 归一化为字典或字符串二选一。"""
        return self.__check_cookie(cookie, name="cookie_tiktok")

    def __check_cookie(self, cookie: dict | str, name="cookie") -> tuple[dict, str]:
        """保留 Cookie 的原始表示，并为另一种表示返回空值。"""
        if isinstance(cookie, dict):
            return cookie, ""
        elif isinstance(cookie, str):
            return {}, cookie
        else:
            self.logger.warning(_("{name} 参数格式错误").format(name=name))
        return {}, ""

    def __get_cookie(
        self,
        cookie: dict,
    ) -> dict:
        """返回字典形式的抖音 Cookie。"""
        return self.__check_cookie(cookie)[0]

    def __get_cookie_cache(
        self,
        cookie: str,
    ) -> str:
        """返回字符串形式的抖音 Cookie。"""
        return self.__check_cookie(cookie)[1]

    def __get_cookie_tiktok(
        self,
        cookie: dict,
    ) -> dict:
        """返回字典形式的 TikTok Cookie。"""
        return self.__check_cookie_tiktok(cookie)[0]

    def __get_cookie_tiktok_cache(
        self,
        cookie: str,
    ) -> str:
        """返回字符串形式的 TikTok Cookie。"""
        return self.__check_cookie_tiktok(cookie)[1]

    def __add_cookie(
        self,
        parameters: tuple[dict, ...],
        cookie: dict | str,
    ) -> None | str:
        """按 Cookie 原始表示合并生成参数。

        参数日志包含令牌原值，部署时应限制日志访问权限和保留周期。
        """
        if isinstance(cookie, dict):
            for i in parameters:
                if i:
                    self.logger.info(
                        f"参数: {i}",
                        False,
                    )
                    cookie |= i
            return None
        elif isinstance(cookie, str):
            for i in parameters:
                if i:
                    self.logger.info(
                        f"参数: {i}",
                        False,
                    )
                    cookie += f"; {cookie_dict_to_str(i)}"
            return cookie
        raise DownloaderError

    async def __get_tt_wid_params(self) -> dict:
        """限时请求抖音 ttwid，失败时返回空参数。"""
        if tt_wid := await TtWid.get_tt_wid(
            self.logger,
            self.headers_params,
            proxy=self.proxy,
            timeout=min(self.timeout, 3),
        ):
            self.logger.info(f"抖音 {TtWid.NAME} 请求值: {tt_wid[TtWid.NAME]}", False)
            return tt_wid
        return {}

    async def __get_tt_wid_params_tiktok(self) -> dict:
        """优先复用本地 twc_tiktok，并请求 TikTok ttwid。"""
        if tt_wid := await TtWidTikTok.get_tt_wid(
            self.logger,
            self.headers_params_tiktok,
            self.twc_tiktok
            or f"{TtWidTikTok.NAME}={
                self.cookie_dict_tiktok.get(TtWidTikTok.NAME, '')
                or self.get_cookie_value(
                    self.cookie_str_tiktok,
                    TtWidTikTok.NAME,
                )
            }",
            proxy=self.proxy_tiktok,
        ):
            self.logger.info(
                f"TikTok {TtWidTikTok.NAME} 请求值: {tt_wid[TtWidTikTok.NAME]}", False
            )
            return tt_wid
        return {}

    def __check_root(self, root: str) -> Path:
        """验证下载目录；可创建时创建，否则回退到项目运行目录。"""
        if not root:
            return self.ROOT
        if (r := Path(root)).is_dir():
            self.logger.info(f"root 参数已设置为 {root}", False)
            return r
        if r := self.__check_root_again(r):
            self.logger.info(f"root 参数已设置为 {r}", False)
            return r
        self.logger.warning(
            _(
                "root 参数 {root} 不是有效的文件夹路径，程序将使用项目根路径作为储存路径"
            ).format(root=root),
        )
        return self.ROOT

    @staticmethod
    def __check_root_again(root: Path) -> bool | Path:
        """仅在父目录存在时创建下载目录。"""
        if root.resolve().parent.is_dir():
            root.mkdir()
            return root
        return False

    def __check_folder_name(self, folder_name: str) -> str:
        """清理下载文件夹名称，空结果回退为 Download。"""
        if folder_name := self.CLEANER.filter_name(
            folder_name,
        ):
            self.logger.info(f"folder_name 参数已设置为 {folder_name}", False)
            return folder_name
        self.logger.warning(
            _(
                "folder_name 参数 {folder_name} 不是有效的文件夹名称，程序将使用默认值：Download"
            ).format(folder_name=folder_name),
        )
        return "Download"

    def __check_name_format(self, name_format: str) -> list[str]:
        """验证文件名字段序列，非法字段触发默认格式。"""
        name_keys = name_format.strip().split(" ")
        if all(i in self.NAME_KEYS for i in name_keys):
            self.logger.info(f"name_format 参数已设置为 {name_format}", False)
            return name_keys
        else:
            self.logger.warning(
                _(
                    "name_format 参数 {name_format} 设置错误，程序将使用默认值：创建时间 作品类型 账号昵称 作品描述"
                ).format(name_format=name_format)
            )
            return ["create_time", "type", "nickname", "desc"]

    def __check_date_format(self, date_format: str) -> str:
        """用当前时间验证 strftime 格式，失败时返回默认格式。"""
        try:
            strftime(date_format, localtime())
            self.logger.info(f"date_format 参数已设置为 {date_format}", False)
            return date_format
        except ValueError:
            self.logger.warning(
                _(
                    "date_format 参数 {date_format} 设置错误，程序将使用默认值：年-月-日 时:分:秒"
                ).format(date_format=date_format),
            )
            return "%Y-%m-%d %H:%M:%S"

    def __check_split(self, split: str) -> str:
        """拒绝会使生成文件名失效的分隔字符。"""
        for i in split:
            if i in self.CLEANER.rule.keys():
                self.logger.warning(
                    _("split 参数 {split} 包含非法字符，程序将使用默认值：-").format(
                        split=split
                    )
                )
                return "-"
        self.logger.info(f"split 参数已设置为 {split}", False)
        return split

    def __check_proxy_tiktok(
        self,
        proxy: str | None | dict,
    ) -> str | None:
        """通过 TikTok 首页验证代理可用性。"""
        return self.__check_proxy(
            proxy,
            "https://www.tiktok.com/explore",
            "TikTok",
            self.tiktok_platform,
        )

    def __check_proxy(
        self,
        proxy: str | None | dict,
        url="https://www.douyin.com/?recommend=1",
        remark=_("抖音"),
        enable=True,
    ) -> str | None:
        """请求目标平台首页验证代理；失败或平台关闭时禁用代理。"""
        if enable and proxy:
            # 旧配置可能按协议保存代理字典，先读取 https:// 键维持兼容。
            if isinstance(proxy, dict):
                self.console.warning(
                    _("{remark}代理参数应为字符串格式，未来不再支持字典格式").format(
                        remark=remark
                    )
                )
                if not (proxy := proxy.get("https://")):
                    return None
            try:
                response = get(
                    url,
                    headers=self.HEADERS,
                    follow_redirects=True,
                    timeout=TIMEOUT,
                    proxy=proxy,
                )
                response.raise_for_status()
                self.logger.info(
                    _("{remark}代理 {proxy} 测试成功").format(
                        remark=remark, proxy=proxy
                    )
                )
                return proxy
            except TimeoutException:
                self.logger.warning(
                    _("{remark}代理 {proxy} 测试超时").format(
                        remark=remark, proxy=proxy
                    )
                )
                return None
            except (
                RequestError,
                HTTPStatusError,
            ) as e:
                self.logger.warning(
                    _("{remark}代理 {proxy} 测试失败：{error}").format(
                        remark=remark, proxy=proxy, error=e
                    ),
                )
                return None
        return None

    def __check_max_size(self, max_size: int) -> int:
        """将单文件大小下限收敛到零。"""
        max_size = max(max_size, 0)
        self.logger.info(f"max_size 参数已设置为 {max_size}", False)
        return max_size

    def __check_chunk(self, chunk: int) -> int:
        """验证下载分块大小。"""
        return self.__check_number_value(
            chunk,
            "chunk",
            1024 * 128,
            1024 * 1024 * 2,
        )

    def __check_max_retry(self, max_retry: int) -> int:
        """验证最大重试次数。"""
        return self.__check_number_value(
            max_retry,
            "max_retry",
            0,
            5,
        )

    def __check_max_pages(self, max_pages: int) -> int:
        """将非正整数页数回退为近似不限页。"""
        if isinstance(max_pages, int) and max_pages > 0:
            self.logger.info(f"max_pages 参数已设置为 {max_pages}", False)
            return max_pages
        elif max_pages != 0:
            self.logger.warning(
                _(
                    "max_pages 参数 {max_pages} 设置错误，程序将使用默认值：99999"
                ).format(max_pages=max_pages),
            )
        return 99999

    def __check_timeout(self, timeout: int | float) -> int | float:
        """验证请求超时秒数。"""
        return self.__check_number_value(
            timeout,
            "timeout",
            2,
            10,
        )

    def __check_storage_format(self, storage_format: str) -> str:
        """仅接受当前记录器支持的 csv、xlsx 和 sql。"""
        if storage_format in ["csv", "xlsx", "sql"]:
            self.logger.info(f"storage_format 参数已设置为 {storage_format}", False)
            return storage_format
        if not storage_format:
            self.logger.info(
                "storage_format 参数未设置，程序不会储存任何数据至文件", False
            )
        else:
            self.logger.warning(
                _(
                    "storage_format 参数 {storage_format} 设置错误，程序默认不会储存任何数据至文件"
                ).format(storage_format=storage_format),
            )
        return ""

    @staticmethod
    def __check_run_command(run_command: str) -> list:
        """拆分后逆序保存附加命令参数。"""
        return run_command.split()[::-1] if run_command else []

    async def update_params(self) -> None:
        """刷新双平台的 msToken 与 ttwid，并同步 API 参数和 Cookie 请求头。"""
        API, APITikTok = _get_api_classes()

        if self.douyin_platform:
            if any(
                (
                    self.cookie_dict,
                    self.cookie_str,
                )
            ):
                self.console.info(
                    _("正在更新抖音参数，请稍等..."),
                )
                # 本地 Cookie 最可信，其次复用 API 缓存，最后才生成离线兜底值。
                local_ms_token = self.cookie_dict.get(MsToken.NAME) or self.get_cookie_value(
                    self.cookie_str,
                    MsToken.NAME,
                )
                cached_ms_token = ""
                if API and isinstance(getattr(API, "params", None), dict):
                    cached_ms_token = API.params.get("msToken", "")
                if local_ms_token:
                    ms_token = {MsToken.NAME: local_ms_token}
                elif cached_ms_token:
                    ms_token = {MsToken.NAME: cached_ms_token}
                else:
                    ms_token = await self.__get_token_params()
                local_tt_wid = self.cookie_dict.get(TtWid.NAME) or self.get_cookie_value(
                    self.cookie_str,
                    TtWid.NAME,
                )
                if local_tt_wid:
                    tt_wid = {TtWid.NAME: local_tt_wid}
                else:
                    tt_wid = await self.__get_tt_wid_params()
                # 查询参数与 Cookie 必须使用同一组令牌，避免签名上下文不一致。
                if API and ms_token:
                    API.params["msToken"] = ms_token.get(MsToken.NAME, "")
                params_to_add = [p for p in (ms_token, tt_wid) if p]
                await self.__update_cookie(
                    tuple(params_to_add),
                    (
                        self.headers,
                        self.headers_download,
                    ),
                    self.cookie_dict,
                    self.cookie_str,
                )
                self.console.info(
                    _("抖音参数更新完毕！"),
                )
            else:
                self.logger.warning(
                    _("配置文件 cookie 参数未设置，抖音平台功能可能无法正常使用")
                )
        if self.tiktok_platform:
            if any(
                (
                    self.cookie_dict_tiktok,
                    self.cookie_str_tiktok,
                )
            ):
                self.console.info(
                    _("正在更新 TikTok 参数，请稍等..."),
                )
                ms_token = await self.__get_token_params_tiktok()
                tt_wid = await self.__get_tt_wid_params_tiktok()
                # TikTok API 参数与请求头同样需要共享令牌状态。
                if APITikTok and ms_token:
                    APITikTok.params["msToken"] = ms_token.get(MsTokenTikTok.NAME, "")
                params_to_add = [p for p in (ms_token, tt_wid) if p]
                await self.__update_cookie(
                    tuple(params_to_add),
                    (
                        self.headers_tiktok,
                        self.headers_download_tiktok,
                    ),
                    self.cookie_dict_tiktok,
                    self.cookie_str_tiktok,
                )
                self.console.info(
                    _("TikTok 参数更新完毕！"),
                )
            else:
                self.logger.warning(
                    _(
                        "配置文件 cookie_tiktok 参数未设置，TikTok 平台功能可能无法正常使用"
                    )
                )

    async def update_params_offline(self) -> None:
        """离线参数刷新尚未启用，保留异步接口兼容。"""
        pass

    async def __update_cookie(
        self,
        parameters: tuple[dict, ...],
        headers: tuple[dict, ...],
        cookie_dict: dict,
        cookie_str: str,
    ) -> None:
        """合并生成参数，并将同一 Cookie 写入一组请求头。"""
        cookie = self.__add_cookie(
            parameters,
            cookie_dict or cookie_str,
        )
        if not isinstance(cookie, str):
            cookie = cookie_dict_to_str(cookie_dict)
        for i in headers:
            i["Cookie"] = cookie

    def set_headers_cookie(
        self,
    ) -> None:
        """把现有双平台 Cookie 写入数据与下载请求头。"""
        if self.cookie_dict:
            cookie = cookie_dict_to_str(self.cookie_dict)
            self.headers["Cookie"] = cookie
            self.headers_download["Cookie"] = cookie
        elif self.cookie_str:
            self.headers["Cookie"] = self.cookie_str
            self.headers_download["Cookie"] = self.cookie_str
        if self.cookie_dict_tiktok:
            cookie = cookie_dict_to_str(self.cookie_dict_tiktok)
            self.headers_tiktok["Cookie"] = cookie
            self.headers_download_tiktok["Cookie"] = cookie
        elif self.cookie_str_tiktok:
            self.headers_tiktok["Cookie"] = self.cookie_str_tiktok
            self.headers_download_tiktok["Cookie"] = self.cookie_str_tiktok

    def set_download_headers(self) -> None:
        """设置双平台下载请求所需的最小 Cookie。"""
        self.__update_download_headers()
        self.__update_download_headers_tiktok()

    def __update_download_headers(self) -> None:
        """写入抖音下载接口依赖的屏幕尺寸 Cookie。"""
        self.headers_download["Cookie"] = "dy_swidth=1536; dy_sheight=864"

    def __update_download_headers_tiktok(self) -> None:
        """优先使用 tt_chain_token，否则沿用完整 TikTok Cookie。"""
        key = "tt_chain_token"
        if tk := self.cookie_dict_tiktok.get(
            key,
        ):
            self.headers_download_tiktok["Cookie"] = f"{key}={tk}"
        else:
            self.headers_download_tiktok["Cookie"] = self.cookie_str_tiktok

    async def __get_token_params(self) -> dict:
        """读取本地 msToken；缺失时生成离线兜底值。"""
        ms_token = self.cookie_dict.get(MsToken.NAME) or self.get_cookie_value(
            self.cookie_str,
            MsToken.NAME,
        )
        if ms_token:
            self.logger.info(
                f"抖音 MsToken 本地值: {ms_token}",
                False,
            )
            return {MsToken.NAME: ms_token}

        # 不在启动关键路径请求远程 msToken，避免网络抖动拖慢初始化。
        fake_ms_token = MsToken.get_fake_ms_token()
        self.logger.info(
            f"抖音 MsToken 使用本地兜底值: {fake_ms_token[MsToken.NAME]}",
            False,
        )
        return fake_ms_token

    async def __get_token_params_tiktok(self) -> dict:
        """仅读取本地 TikTok msToken，缺失时返回空参数。"""
        if not (
            m := (
                self.cookie_dict_tiktok.get(MsTokenTikTok.NAME)
                or self.get_cookie_value(
                    self.cookie_str_tiktok,
                    MsTokenTikTok.NAME,
                )
            )
        ):
            self.logger.warning(
                _("TikTok cookie 缺少 {name} 键值对，请尝试重新写入 cookie").format(
                    name=MsTokenTikTok.NAME
                )
            )
            return {}
        return {MsTokenTikTok.NAME: m}

    def set_uif_id(
        self,
    ) -> None:
        """UIFID 同步尚未启用，保留公开接口兼容。"""
        pass

    @staticmethod
    def __generate_ffmpeg_object(ffmpeg_path: str) -> Any:
        """FFMPEG 对象构造尚未启用，保留内部调用形态。"""
        return None

    def get_settings_data(self) -> dict:
        """序列化当前可持久化配置。"""
        return {
            "accounts_urls": [vars(i) for i in self.accounts_urls],
            "accounts_urls_tiktok": [vars(i) for i in self.accounts_urls_tiktok],
            "mix_urls": [vars(i) for i in self.mix_urls],
            "mix_urls_tiktok": [vars(i) for i in self.mix_urls_tiktok],
            "owner_url_tiktok": self.owner_url_tiktok,
            "root": str(self.root.resolve()),
            "folder_name": self.folder_name,
            "name_format": " ".join(self.name_format),
            "desc_length": self.desc_length,
            "name_length": self.name_length,
            "date_format": self.date_format,
            "split": self.split,
            "folder_mode": self.folder_mode,
            "music": self.music,
            "truncate": self.truncate,
            "storage_format": self.storage_format,
            "cookie": self.cookie_str or self.cookie_dict,
            "cookie_tiktok": self.cookie_str_tiktok or self.cookie_dict_tiktok,
            "dynamic_cover": self.dynamic_cover,
            "static_cover": self.static_cover,
            "proxy": self.proxy,
            "proxy_tiktok": self.proxy_tiktok,
            "twc_tiktok": self.twc_tiktok,
            "download": self.download,
            "max_size": self.max_size,
            "chunk": self.chunk,
            "max_retry": self.max_retry,
            "max_pages": self.max_pages,
            "run_command": " ".join(self.run_command[::-1]),
            "ffmpeg": "",
        }

    async def set_settings_data(
        self,
        data: dict,
    ) -> None:
        """按 URL、Cookie、浏览器、代理和通用参数分组应用配置。"""
        self.set_urls_params(
            data.pop("accounts_urls"),
            data.pop("mix_urls"),
            data.pop("owner_url"),
            data.pop("accounts_urls_tiktok"),
            data.pop("mix_urls_tiktok"),
            data.pop("owner_url_tiktok"),
        )
        self.set_cookie(
            data.pop(
                "cookie",
            ),
            data.pop(
                "cookie_tiktok",
            ),
        )
        self.set_browser_info(
            data.pop(
                "browser_info",
            ),
            data.pop(
                "browser_info_tiktok",
            ),
        )
        await self.set_proxy(
            data.pop(
                "proxy",
            ),
            data.pop(
                "proxy_tiktok",
            ),
        )
        self.set_general_params(data)

    async def __update_cookie_data(self, data: dict) -> None:
        """从浏览器 Cookie 数据提取双平台凭据并刷新令牌。"""
        for i, j in zip(("cookie", "cookie_tiktok"), (_("抖音"), "TikTok")):
            if c := data.get(i):
                setattr(
                    self, i, self.cookie_object.extract(c, False, key=i, platform=j)
                )
        await self.update_params()

    @staticmethod
    def check_urls_params(data: list[dict]) -> list[Any]:
        """批量 URL 参数解析尚未启用，保留接口并返回空列表。"""
        return []

    @staticmethod
    def check_url_params(data: dict) -> Any:
        """将单个 URL 配置归一化为包含 url 与 mark 的命名空间。"""
        if not data.get("url"):
            return SimpleNamespace(
                mark="",
                url="",
            )
        if not isinstance(data.get("mark"), str):
            data["mark"] = ""
        return SimpleNamespace(**data)

    def set_urls_params(
        self,
        accounts_urls: list[dict],
        mix_urls: list[dict],
        owner_url: dict,
        accounts_urls_tiktok: list[dict],
        mix_urls_tiktok: list[dict],
        owner_url_tiktok: dict,
    ):
        """更新非空的账号、合集与单账号 URL 配置。"""
        if accounts_urls:
            self.accounts_urls = self.check_urls_params(accounts_urls)
        if accounts_urls_tiktok:
            self.accounts_urls_tiktok = self.check_urls_params(accounts_urls_tiktok)
        if mix_urls:
            self.mix_urls = self.check_urls_params(mix_urls)
        if mix_urls_tiktok:
            self.mix_urls_tiktok = self.check_urls_params(mix_urls_tiktok)
        if owner_url:
            self.owner_url = self.check_url_params(owner_url)

    def set_cookie(
        self, cookie: str | dict[str, str], cookie_tiktok: str | dict[str, str]
    ):
        """更新非空的双平台 Cookie 及其登录态标记。"""
        if cookie:
            self.cookie_dict, self.cookie_str = self.__check_cookie(cookie)
            self.cookie_state: bool = self.__check_cookie_state()
            self.set_uif_id()
        if cookie_tiktok:
            self.cookie_dict_tiktok, self.cookie_str_tiktok = (
                self.__check_cookie_tiktok(
                    cookie_tiktok,
                )
            )
            self.cookie_tiktok_state: bool = self.__check_cookie_state(True)
            self.__update_download_headers_tiktok()

    def set_general_params(self, data: dict[str, Any]) -> None:
        """对非空通用配置调用对应校验器。"""
        for i, j in data.items():
            if j is not None:
                self.__CHECK[i](j)

    async def set_proxy(self, proxy: str | None, proxy_tiktok: str | None):
        """验证新代理，关闭旧客户端后按平台重新创建客户端。"""
        if isinstance(proxy, str):
            self.proxy: str | None = self.__check_proxy(
                proxy,
                remark=_("抖音"),
                enable=self.douyin_platform,
            )
        if isinstance(proxy_tiktok, str):
            self.proxy_tiktok: str | None = self.__check_proxy_tiktok(proxy_tiktok)
        await self.close_client()
        self.client = (
            create_client(
                timeout=self.timeout,
                proxy=self.proxy,
            )
            if self.douyin_platform
            else None
        )
        self.client_tiktok = (
            create_client(
                timeout=self.timeout,
                proxy=self.proxy_tiktok,
            )
            if self.tiktok_platform
            else None
        )

    @staticmethod
    def merge_browser_info(
        browser_info: dict,
        new_info: dict,
    ) -> dict:
        """用新浏览器字段覆盖同名旧字段。"""
        return browser_info | new_info

    def set_browser_info(self, browser_info: dict, browser_info_tiktok: dict):
        """合并双平台浏览器指纹信息。"""
        self.browser_info = self.merge_browser_info(
            self.browser_info,
            browser_info or {},
        )
        self.browser_info_tiktok = self.merge_browser_info(
            self.browser_info_tiktok,
            browser_info_tiktok or {},
        )

    @staticmethod
    def check_str(value: str) -> str:
        """非字符串值统一转为空串。"""
        return value if isinstance(value, str) else ""

    async def close_client(self) -> None:
        """关闭当前存在的双平台异步客户端。"""
        if self.client is not None:
            await self.client.aclose()
        if self.client_tiktok is not None:
            await self.client_tiktok.aclose()

    def __generate_folders(self):
        """迁移旧缓存后确保用户缓存目录存在。"""
        self.compatible()
        self.cache.mkdir(exist_ok=True)

    def __set_browser_info(
        self,
        info: dict[str, str],
    ) -> None:
        """同步抖音 UA 到各请求头，并重建 a_bogus 签名器。"""
        self.logger.info(f"抖音浏览器信息: {info}", False)
        if ua := info.get(
            "User-Agent",
        ):
            for i in (
                self.headers,
                self.headers_download,
                self.headers_params,
                self.headers_qrcode,
            ):
                i["User-Agent"] = ua
        else:
            ua = USERAGENT
        # a_bogus 会把 UA 纳入签名，签名器必须与实际请求头保持一致。
        self.ab = ABogus(
            ua,
            info.get(
                "browser_platform",
            ),
        )

    def __set_browser_info_tiktok(
        self,
        info: dict,
    ):
        """同步 TikTok UA 到数据、下载和参数请求头。"""
        self.logger.info(f"TikTok 浏览器信息: {info}", False)
        if ua := info.get(
            "User-Agent",
        ):
            for i in (
                self.headers_tiktok,
                self.headers_download_tiktok,
                self.headers_params_tiktok,
            ):
                i["User-Agent"] = ua

    def __check_truncate(self, truncate: int) -> int:
        """验证文本截断宽度。"""
        return self.__check_number_value(
            truncate,
            "truncate",
            25,
            50,
        )

    def __check_name_length(self, name_length: int) -> int:
        """验证生成文件名的长度上限。"""
        return self.__check_number_value(
            name_length,
            "name_length",
            32,
            128,
        )

    def __check_desc_length(self, desc_length: int) -> int:
        """验证作品描述的截断长度。"""
        return self.__check_number_value(
            desc_length,
            "desc_length",
            16,
            64,
        )

    def __check_number_value(
        self, value: int, name: str, minimum: int, default: int
    ) -> int:
        """校验整数下限，类型或范围不符时使用默认值。"""
        if isinstance(value, int):
            if value >= minimum:
                self.logger.info(f"{name} 参数已设置为 {value}", False)
                return value
            self.logger.warning(
                _("{key} 参数 {value} 设置过小，程序将使用默认值：{default}").format(
                    key=name,
                    value=value,
                    default=default,
                ),
            )
            return default
        self.logger.warning(
            _("{key} 参数 {value} 设置错误，程序将使用默认值：{default}").format(
                key=name,
                value=value,
                default=default,
            ),
        )
        return default

    def __check_live_qualities(self, live_qualities: str) -> str:
        """验证直播清晰度配置为字符串。"""
        if isinstance(live_qualities, str):
            self.logger.info(f"live_qualities 参数已设置为 {live_qualities}", False)
            return live_qualities
        self.logger.warning(
            _("live_qualities 参数 {live_qualities} 设置错误").format(
                live_qualities=live_qualities
            ),
        )
        return ""

    def __check_cookie_state(self, tiktok=False) -> bool:
        """检查 Cookie 中是否包含登录态标记键。"""
        if tiktok:
            return (self.cookie_object.STATE_KEY in self.cookie_dict_tiktok) or (
                self.cookie_object.STATE_KEY in self.cookie_str_tiktok
            )
        return (self.cookie_object.STATE_KEY in self.cookie_dict) or (
            self.cookie_object.STATE_KEY in self.cookie_str
        )

    @staticmethod
    def get_cookie_value(cookie_str: str, key: str, return_key=False) -> str:
        """从 Cookie 字符串读取键值；return_key=True 时保留 key= 前缀。"""
        cookies = {}
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if not pair:
                continue
            # 值中可能含等号，因此只分割一次。
            key_value = pair.split("=", 1)
            if len(key_value) != 2:
                continue
            k, v = key_value[0].strip(), key_value[1].strip()
            cookies[k] = v

        value = cookies.get(key)
        if value is None:
            return ""

        return f"{key}={value}" if return_key else value

    def compatible(self):
        """仅在新目录不存在时迁移旧 Cache，避免覆盖现有用户缓存。"""
        if (
            old := self.ROOT.parent.joinpath("Cache")
        ).exists() and not self.cache.exists():
            move(old, self.cache)
