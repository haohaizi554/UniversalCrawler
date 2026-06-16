"""Shared file operation policy with retry-aware Windows friendly semantics."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from app.exceptions import FileOperationError

T = TypeVar("T")


@dataclass(slots=True, frozen=True)
class FileRetryPolicy:
    """Retry policy for transient file lock failures."""

    max_attempts: int = 10
    retry_delay_sec: float = 0.2


class FileOpPolicy:
    """Centralized file operation policy for rename/remove style mutations."""

    def __init__(self, retry_policy: FileRetryPolicy | None = None) -> None:
        self.retry_policy = retry_policy or FileRetryPolicy()

    def rename(self, source_path: str, target_path: str, *, replace_existing: bool = False) -> tuple[str, str]:
        """Rename a file with transient PermissionError retry support."""

        def _rename() -> tuple[str, str]:
            if replace_existing and os.path.exists(target_path):
                self.remove(target_path, missing_ok=True)
            os.rename(source_path, target_path)
            return source_path, target_path

        return self._run_with_retry(_rename, error_message="重命名文件失败")

    def remove(self, file_path: str, *, missing_ok: bool = False) -> bool:
        """Remove a file with transient PermissionError retry support."""
        if not file_path or not os.path.exists(file_path):
            return bool(missing_ok)

        def _remove() -> bool:
            os.remove(file_path)
            return True

        return self._run_with_retry(_remove, error_message="删除文件失败")

    def _run_with_retry(self, operation: Callable[[], T], *, error_message: str) -> T:
        """Retry only transient permission errors and surface a stable domain error."""
        last_error: OSError | None = None
        attempts = max(1, int(self.retry_policy.max_attempts))
        delay = max(0.0, float(self.retry_policy.retry_delay_sec))
        for attempt in range(attempts):
            try:
                return operation()
            except PermissionError as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(delay)
                    continue
                break
            except OSError as exc:
                raise FileOperationError(str(exc)) from exc
        raise FileOperationError(str(last_error) if last_error else error_message)
