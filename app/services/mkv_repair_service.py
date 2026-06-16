"""MKV playback repair helpers."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.downloaders.external import FFmpegExternalTool, build_hidden_startupinfo
from app.utils.runtime_paths import user_cache_root


ProcessRunner = Callable[[list[str]], subprocess.CompletedProcess]


@dataclass(frozen=True, slots=True)
class MkvRepairResult:
    source_path: str
    playable_path: str
    repaired: bool
    message: str = ""


class MkvPlaybackRepairService:
    """Build seekable MKV playback cache files by remuxing with ffmpeg."""

    def __init__(
        self,
        *,
        cache_root: Path | None = None,
        ffmpeg_resolver: Callable[[], str | None] | None = None,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self.cache_root = cache_root or (user_cache_root() / "mkv_repair")
        self.ffmpeg_resolver = ffmpeg_resolver or FFmpegExternalTool.resolve_executable
        self.process_runner = process_runner or self._run_process

    @staticmethod
    def is_mkv_path(path: str | os.PathLike[str]) -> bool:
        return Path(path).suffix.lower() == ".mkv"

    def repair_for_playback(self, source_path: str | os.PathLike[str]) -> MkvRepairResult:
        source = Path(source_path)
        source_text = str(source)
        if not self.is_mkv_path(source):
            return MkvRepairResult(source_text, source_text, False, "不是 MKV 文件")
        if not source.is_file():
            return MkvRepairResult(source_text, source_text, False, "文件不存在")

        ffmpeg = self.ffmpeg_resolver()
        if not ffmpeg:
            return MkvRepairResult(source_text, source_text, False, "未找到 ffmpeg，无法修复 MKV 索引")

        self.cache_root.mkdir(parents=True, exist_ok=True)
        target = self._cache_path_for(source)
        if target.is_file() and target.stat().st_size > 0:
            return MkvRepairResult(source_text, str(target), True, "已使用 MKV 修复缓存")

        temp = target.with_name(f"{target.stem}.tmp{target.suffix}")
        try:
            if temp.exists():
                temp.unlink()
            command = self.build_repair_command(ffmpeg, source, temp)
            completed = self.process_runner(command)
            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip()
                message = stderr.splitlines()[-1] if stderr else f"ffmpeg 退出码 {completed.returncode}"
                return MkvRepairResult(source_text, source_text, False, message)
            if not temp.is_file() or temp.stat().st_size <= 0:
                return MkvRepairResult(source_text, source_text, False, "ffmpeg 未生成有效修复文件")
            os.replace(temp, target)
            return MkvRepairResult(source_text, str(target), True, "已重建 MKV 索引并使用播放缓存")
        except Exception as exc:
            return MkvRepairResult(source_text, source_text, False, str(exc))
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass

    @staticmethod
    def build_repair_command(ffmpeg: str, source: Path, target: Path) -> list[str]:
        return [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "+genpts",
            "-i",
            str(source),
            "-map",
            "0",
            "-c",
            "copy",
            "-map_metadata",
            "0",
            "-avoid_negative_ts",
            "make_zero",
            "-f",
            "matroska",
            str(target),
        ]

    def _cache_path_for(self, source: Path) -> Path:
        stat = source.stat()
        try:
            resolved = source.resolve()
        except OSError:
            resolved = source.absolute()
        identity = f"{os.path.normcase(str(resolved))}|{stat.st_size}|{stat.st_mtime_ns}"
        digest = hashlib.sha1(identity.encode("utf-8", "surrogatepass")).hexdigest()[:20]
        return self.cache_root / f"mkv_{digest}.mkv"

    @staticmethod
    def _run_process(command: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30 * 60,
            startupinfo=build_hidden_startupinfo(),
            check=False,
        )
