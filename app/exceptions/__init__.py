from .base import AppError
from .config import ConfigError, ConfigReadError, ConfigValidationError, ConfigWriteError
from .downloader import (
    DownloaderError,
    DownloaderStoppedError,
    ExternalToolError,
    ExternalToolNotFoundError,
    MergeError,
    StreamDownloadError,
)
from .service import DebugActionError, FileOperationError, MediaScanError, ServiceError
from .spider import (
    CookieLoadError,
    CookieSaveError,
    InvalidCookieStateError,
    LoginCancelledError,
    LoginCheckError,
    LoginTimeoutError,
    SpiderAuthError,
    SpiderError,
    SpiderParseError,
    StreamResolveError,
)

__all__ = [
    "AppError",
    "ConfigError",
    "ConfigReadError",
    "ConfigValidationError",
    "ConfigWriteError",
    "DownloaderError",
    "DownloaderStoppedError",
    "ExternalToolError",
    "ExternalToolNotFoundError",
    "MergeError",
    "StreamDownloadError",
    "ServiceError",
    "MediaScanError",
    "FileOperationError",
    "DebugActionError",
    "SpiderError",
    "SpiderAuthError",
    "CookieLoadError",
    "CookieSaveError",
    "InvalidCookieStateError",
    "LoginCancelledError",
    "LoginCheckError",
    "LoginTimeoutError",
    "SpiderParseError",
    "StreamResolveError",
]
