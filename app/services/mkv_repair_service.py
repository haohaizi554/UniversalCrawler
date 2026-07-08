"""Local video playback repair helpers."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.downloaders.external import FFmpegExternalTool, build_hidden_startupinfo
from app.debug_logger import debug_logger
from app.utils.runtime_paths import user_cache_root

ProcessRunner = Callable[[list[str]], subprocess.CompletedProcess]
RepairProgressCallback = Callable[[int, str], None]
RepairCancelCheck = Callable[[], bool]

@dataclass(frozen=True, slots=True)
class MkvRepairResult:
    source_path: str
    playable_path: str
    repaired: bool
    message: str = ""

@dataclass(frozen=True, slots=True)
class RepairCommitResult:
    source_path: str
    committed: bool
    message: str = ""

class MkvPlaybackRepairService:
    """Build seekable playback cache files and optionally write them back."""

    STALE_TEMP_MAX_AGE_SECONDS = 24 * 60 * 60
    REPAIR_PROCESS_TIMEOUT_SECONDS = 60

    REPAIRABLE_VIDEO_EXTENSIONS = (
        ".mkv",
        ".mp4",
        ".avi",
        ".mov",
        ".flv",
        ".wmv",
        ".m4v",
        ".webm",
        ".ts",
    )

    def __init__(
        self,
        *,
        cache_root: Path | None = None,
        ffmpeg_resolver: Callable[[], str | None] | None = None,
        process_runner: ProcessRunner | None = None,
        cleanup_on_init: bool = True,
    ) -> None:
        self.cache_root = cache_root or (user_cache_root() / "mkv_repair")
        self.ffmpeg_resolver = ffmpeg_resolver or FFmpegExternalTool.resolve_executable
        self.process_runner = process_runner
        if cleanup_on_init:
            self.cleanup_stale_cache_files()

    @staticmethod
    def is_mkv_path(path: str | os.PathLike[str]) -> bool:
        return Path(path).suffix.lower() == ".mkv"

    @classmethod
    def is_repairable_path(cls, path: str | os.PathLike[str]) -> bool:
        return Path(path).suffix.lower() in cls.REPAIRABLE_VIDEO_EXTENSIONS

    def cached_playable_path(self, source_path: str | os.PathLike[str]) -> str:
        """Return the repaired cache path if one already exists."""
        source = Path(source_path)
        source_text = str(source)
        if not self.is_repairable_path(source) or not source.is_file():
            return source_text
        target = self._cache_path_for(source)
        if target.is_file() and target.stat().st_size > 0:
            return str(target)
        return source_text

    def repair_for_playback(
        self,
        source_path: str | os.PathLike[str],
        *,
        progress_callback: RepairProgressCallback | None = None,
        cancel_check: RepairCancelCheck | None = None,
    ) -> MkvRepairResult:
        source = Path(source_path)
        source_text = str(source)
        if not self.is_repairable_path(source):
            return MkvRepairResult(source_text, source_text, False, "不是可修复的视频文件")
        if not source.is_file():
            return MkvRepairResult(source_text, source_text, False, "文件不存在")

        ffmpeg = self.ffmpeg_resolver()
        if not ffmpeg:
            return MkvRepairResult(source_text, source_text, False, "未找到 ffmpeg，无法修复播放索引")

        self.cache_root.mkdir(parents=True, exist_ok=True)
        target = self._cache_path_for(source)
        if target.is_file() and target.stat().st_size > 0:
            if progress_callback:
                progress_callback(100, "已使用播放修复缓存")
            return MkvRepairResult(source_text, str(target), True, "已使用播放修复缓存")

        temp = self._cache_temp_path_for(target)
        try:
            if temp.exists():
                temp.unlink()
            if progress_callback:
                progress_callback(0, "正在准备播放索引修复")

            command = self.build_repair_command(ffmpeg, source, temp)
            if self.process_runner is not None:
                completed = self.process_runner(command)
            else:
                completed = self._run_process_with_progress(
                    command,
                    temp_path=temp,
                    source_size=source.stat().st_size,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )

            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip()
                message = stderr.splitlines()[-1] if stderr else f"ffmpeg 退出码 {completed.returncode}"
                return MkvRepairResult(source_text, source_text, False, message)
            if not temp.is_file() or temp.stat().st_size <= 0:
                return MkvRepairResult(source_text, source_text, False, "ffmpeg 未生成有效修复文件")

            os.replace(temp, target)
            if progress_callback:
                progress_callback(100, "播放索引修复完成")
            return MkvRepairResult(source_text, str(target), True, "已重建播放索引并使用播放缓存")
        except Exception as exc:
            return MkvRepairResult(source_text, source_text, False, str(exc))
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass

    def write_repair_to_source(
        self,
        source_path: str | os.PathLike[str],
        repaired_path: str | os.PathLike[str],
        *,
        progress_callback: RepairProgressCallback | None = None,
        cancel_check: RepairCancelCheck | None = None,
    ) -> RepairCommitResult:
        """Copy a repaired playback file back over the original using a temp file."""
        source = Path(source_path)
        repaired = Path(repaired_path)
        source_text = str(source)
        try:
            if not repaired.is_file():
                return RepairCommitResult(source_text, False, "修复缓存不存在")
            if self._same_file(source, repaired):
                return RepairCommitResult(source_text, True, "本地文件已是修复版本")
            self.cleanup_stale_source_temp_files(source)
            temp = self._source_commit_temp_path_for(source)
            if temp.exists():
                temp.unlink()
            self._copy_file_with_progress(
                repaired,
                temp,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
            os.replace(temp, source)
            if progress_callback:
                progress_callback(100, "本地文件写回完成")
            return RepairCommitResult(source_text, True, "已写回原文件")
        except Exception as exc:
            try:
                if "temp" in locals() and temp.exists():
                    temp.unlink()
            except OSError:
                pass
            return RepairCommitResult(source_text, False, str(exc))

    def discard_cache_file(self, cache_path: str | os.PathLike[str]) -> bool:
        """Remove a repair cache file if it belongs to this service cache root."""
        path = Path(cache_path)
        try:
            cache_root = self.cache_root.resolve()
            resolved = path.resolve()
        except OSError:
            return False
        if cache_root not in (resolved, *resolved.parents):
            return False
        return self._safe_unlink(resolved)

    def cleanup_stale_cache_files(self, *, max_age_seconds: int | None = None) -> int:
        """Remove old temp files left by an interrupted repair process."""
        if not self.cache_root.exists():
            return 0
        max_age = self.STALE_TEMP_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
        removed = 0
        for path in self.cache_root.glob("*.ucp-repairing.*.tmp*"):
            if self._is_stale(path, max_age) and self._safe_unlink(path):
                removed += 1
        return removed

    def cleanup_stale_source_temp_files(
        self,
        source_path: str | os.PathLike[str],
        *,
        max_age_seconds: int | None = None,
    ) -> int:
        """Remove old same-directory commit temp files for a source file."""
        source = Path(source_path)
        parent = source.parent
        if not parent.exists():
            return 0
        max_age = self.STALE_TEMP_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
        removed = 0
        for path in parent.glob(f".{source.name}.ucp-commit.*.tmp"):
            if self._is_stale(path, max_age) and self._safe_unlink(path):
                removed += 1
        return removed

    @staticmethod
    def build_repair_command(ffmpeg: str, source: Path, target: Path) -> list[str]:
        command = [
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
        ]
        if target.suffix.lower() == ".mp4":
            command.extend(["-movflags", "+faststart", "-f", "mp4"])
        else:
            command.extend(["-f", "matroska"])
        command.append(str(target))
        return command

    def _cache_path_for(self, source: Path) -> Path:
        stat = source.stat()
        try:
            resolved = source.resolve()
        except OSError:
            resolved = source.absolute()
        identity = f"{os.path.normcase(str(resolved))}|{stat.st_size}|{stat.st_mtime_ns}"
        digest = hashlib.sha1(identity.encode("utf-8", "surrogatepass")).hexdigest()[:20]
        return self.cache_root / f"playback_{digest}{self._cache_suffix_for(source)}"

    @staticmethod
    def _cache_temp_path_for(target: Path) -> Path:
        return target.with_name(f"{target.stem}.ucp-repairing.{os.getpid()}.tmp{target.suffix}")

    @staticmethod
    def _source_commit_temp_path_for(source: Path) -> Path:
        return source.with_name(f".{source.name}.ucp-commit.{os.getpid()}.tmp")

    @staticmethod
    def _cache_suffix_for(source: Path) -> str:
        if source.suffix.lower() in {".mp4", ".m4v", ".mov"}:
            return ".mp4"
        return ".mkv"

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        try:
            return left.samefile(right)
        except OSError:
            return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))

    @staticmethod
    def _copy_file_with_progress(
        source: Path,
        target: Path,
        *,
        progress_callback: RepairProgressCallback | None,
        cancel_check: RepairCancelCheck | None,
    ) -> None:
        total_size = max(1, source.stat().st_size)
        copied = 0
        last_progress = -1
        with source.open("rb") as src, target.open("wb") as dst:
            while True:
                if cancel_check and cancel_check():
                    raise RuntimeError("写回已取消")
                chunk = src.read(8 * 1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                copied += len(chunk)
                if progress_callback:
                    progress = min(99, int(copied / total_size * 100))
                    if progress != last_progress:
                        progress_callback(progress, f"正在写回本地文件 {progress}%")
                        last_progress = progress
            dst.flush()
            os.fsync(dst.fileno())

    @staticmethod
    def _is_stale(path: Path, max_age_seconds: int) -> bool:
        try:
            return (time.time() - path.stat().st_mtime) >= max_age_seconds
        except OSError:
            return False

    @staticmethod
    def _safe_unlink(path: Path) -> bool:
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    @staticmethod
    def _run_process(command: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=MkvPlaybackRepairService.REPAIR_PROCESS_TIMEOUT_SECONDS,
            startupinfo=build_hidden_startupinfo(),
            check=False,
        )

    @staticmethod
    def _run_process_with_progress(
        command: list[str],
        *,
        temp_path: Path,
        source_size: int,
        progress_callback: RepairProgressCallback | None,
        cancel_check: RepairCancelCheck | None,
    ) -> subprocess.CompletedProcess:
        if progress_callback is None and cancel_check is None:
            return MkvPlaybackRepairService._run_process(command)

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=build_hidden_startupinfo(),
        )
        last_progress = -1
        deadline = time.monotonic() + MkvPlaybackRepairService.REPAIR_PROCESS_TIMEOUT_SECONDS
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    process.kill()
                    stdout, stderr = process.communicate()
                    return subprocess.CompletedProcess(command, 1, stdout, stderr or "修复超时")
                if cancel_check and cancel_check():
                    process.kill()
                    stdout, stderr = process.communicate()
                    return subprocess.CompletedProcess(command, 1, stdout, stderr or "修复已取消")

                if progress_callback and source_size > 0 and temp_path.exists():
                    try:
                        progress = min(99, max(1, int(temp_path.stat().st_size / source_size * 100)))
                    except OSError:
                        progress = last_progress
                    if progress != last_progress:
                        progress_callback(progress, f"正在修复播放索引 {progress}%")
                        last_progress = progress

                time.sleep(0.5)

            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except Exception:
            try:
                stdout, stderr = process.communicate(timeout=2)
            except Exception:
                stdout, stderr = "", ""
            if process.poll() is None:
                process.kill()
                try:
                    process.communicate(timeout=2)
                except (subprocess.TimeoutExpired, OSError, RuntimeError) as exc:
                    debug_logger.log_exception("MkvPlaybackRepairService", "communicate_after_kill", exc)
            raise
