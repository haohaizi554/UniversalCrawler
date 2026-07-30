"""Descriptor-owned, content-addressed updater generation publication."""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from types import TracebackType

from shared.filesystem_directory_capability import (
    DescriptorPublishReceipt,
    DescriptorPublishStatus,
    FilesystemDirectoryCapability,
    OwnedGenerationHandle,
    is_link_or_reparse,
)

PublishReceipt = DescriptorPublishReceipt
PublishStatus = DescriptorPublishStatus

_HASH_CHUNK_SIZE = 1024 * 1024
_MAX_LABEL_LENGTH = 128
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CLOCK$",
    "CON",
    "CONIN$",
    "CONOUT$",
    "NUL",
    "PRN",
}


class GenerationError(OSError):
    """Base failure for an owned updater generation."""


class GenerationIntegrityError(GenerationError):
    """The bytes on the owned descriptor do not match the signed contract."""


class GenerationCollisionError(GenerationError):
    """A content-addressed target exists but is not the expected generation."""


class GenerationPublishUncertainError(GenerationError):
    """A native publish failed and its durable outcome could not be proven."""

    def __init__(self, receipt: PublishReceipt) -> None:
        super().__init__(
            "exact-generation publication outcome is unknown; do not retry"
        )
        self.receipt = receipt


class PublishedLease:
    """A verified generation descriptor whose lifetime is caller-controlled."""

    def __init__(
        self,
        *,
        descriptor: int,
        name: str,
        size: int,
        sha256: str,
        receipt: PublishReceipt,
    ) -> None:
        self._descriptor = descriptor
        self.name = name
        self.size = size
        self.sha256 = sha256
        self.receipt = receipt
        self._closed = False

    def fileno(self) -> int:
        if self._closed:
            raise OSError("published generation lease is closed")
        return self._descriptor

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        descriptor = self._descriptor
        self._descriptor = -1
        os.close(descriptor)

    def __enter__(self) -> "PublishedLease":
        self.fileno()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, traceback
        try:
            self.close()
        except BaseException as cleanup_error:
            if exc_value is None:
                raise
            if isinstance(exc_value, Exception) and not isinstance(
                cleanup_error,
                Exception,
            ):
                raise
            _attach_note_best_effort(
                exc_value,
                "published generation lease cleanup failed",
            )


class OwnedGeneration:
    """One write-once source that can be published exactly once."""

    def __init__(
        self,
        capability: FilesystemDirectoryCapability,
        native: OwnedGenerationHandle,
    ) -> None:
        self._capability = capability
        self._native = native
        self._state = "writing"
        self._size: int | None = None
        self._sha256: str | None = None

    @classmethod
    def create(
        cls,
        capability: FilesystemDirectoryCapability,
    ) -> "OwnedGeneration":
        if type(capability) is not FilesystemDirectoryCapability:
            raise OSError("owned generation requires a directory capability")
        return cls(capability, capability.create_owned_generation())

    @property
    def stage_name_for_testing(self) -> str | None:
        return self._native.stage_name_for_testing

    def fileno(self) -> int:
        if self._state != "writing":
            raise OSError("owned generation is not writable")
        return self._native.fileno()

    def write(self, payload: bytes | bytearray | memoryview) -> None:
        if self._state != "writing":
            raise OSError("owned generation is not writable")
        try:
            try:
                view = memoryview(payload).cast("B")
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    "owned generation payload must be bytes-like"
                ) from exc
            offset = 0
            while offset < len(view):
                written = os.write(self._native.fileno(), view[offset:])
                if written <= 0:
                    raise OSError("owned generation write made no progress")
                offset += written
        except BaseException:
            self._state = "failed"
            raise

    def finalize(
        self,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        if self._state != "writing":
            raise OSError("owned generation cannot be finalized in this state")
        size = _validated_size(expected_size)
        digest = _validated_sha256(expected_sha256)
        descriptor = self._native.fileno()
        try:
            os.fsync(descriptor)
            _verify_descriptor_generation(
                descriptor,
                expected_size=size,
                expected_sha256=digest,
            )
        except BaseException:
            self._state = "failed"
            raise
        self._size = size
        self._sha256 = digest
        self._state = "verified"

    def publish_content_addressed(self, label: str) -> PublishedLease:
        if self._state != "verified":
            raise OSError("owned generation is not verified")
        safe_label = _validated_generation_label(label)
        assert self._sha256 is not None
        assert self._size is not None
        target_name = f"{self._sha256}-{safe_label}"
        try:
            receipt = self._capability.publish_owned_generation_no_replace(
                self._native,
                target_name,
            )
        except FileExistsError as exc:
            return self._reuse_verified_collision(target_name, exc)
        except OSError as exc:
            if not self._native.publish_attempted:
                self._close_pre_publish_failure(exc)
                raise
            return self._resolve_ambiguous_publish(target_name, exc)
        except BaseException as exc:
            self._consume_source_after_publish_control_flow(exc)
            raise
        return self._reopen_committed_generation(
            target_name,
            receipt,
            operation="post-publish-generation-reopen",
        )

    def close(self) -> None:
        if self._state == "consumed":
            return
        self._state = "consumed"
        self._native.close()

    def __enter__(self) -> "OwnedGeneration":
        self.fileno()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, traceback
        try:
            self.close()
        except BaseException as cleanup_error:
            if exc_value is None:
                raise
            if isinstance(exc_value, Exception) and not isinstance(
                cleanup_error,
                Exception,
            ):
                raise
            _attach_note_best_effort(
                exc_value,
                "owned generation cleanup failed",
            )

    def _reuse_verified_collision(
        self,
        target_name: str,
        collision: FileExistsError,
    ) -> PublishedLease:
        descriptor: int | None = None
        try:
            descriptor = self._capability.open_owned_generation_lease(
                target_name
            )
            _verify_descriptor_generation(
                descriptor,
                expected_size=self._required_size,
                expected_sha256=self._required_sha256,
            )
        except BaseException as exc:
            if descriptor is not None:
                _close_preserving_primary(descriptor, exc)
            self._state = "consumed"
            self._discard_known_collision_preserving(exc)
            if not isinstance(exc, Exception):
                raise
            failure = GenerationCollisionError(
                "content-addressed target is not the verified generation"
            )
            _attach_note_best_effort(
                failure,
                f"native collision:{_safe_exception_type_label(collision)}",
            )
            raise failure from exc
        cleanup_error = self._discard_known_collision()
        if cleanup_error is not None and not isinstance(
            cleanup_error,
            Exception,
        ):
            assert descriptor is not None
            _close_preserving_primary(descriptor, cleanup_error)
            self._state = "consumed"
            raise cleanup_error
        self._state = "consumed"
        assert descriptor is not None
        try:
            receipt = self._capability.verified_existing_receipt(target_name)
            if cleanup_error is not None:
                receipt.diagnostics.append(
                    "collision-source-cleanup:"
                    f"{_safe_exception_type_label(cleanup_error)}"
                )
        except BaseException as exc:
            _close_preserving_primary(descriptor, exc)
            raise
        return self._committed_lease(descriptor, target_name, receipt)

    def _resolve_ambiguous_publish(
        self,
        target_name: str,
        native_error: OSError,
    ) -> PublishedLease:
        confirmation_error: BaseException | None = None
        try:
            same_handle_commit = (
                self._capability.owned_generation_is_published_as(
                    self._native,
                    target_name,
                )
            )
        except BaseException as exc:
            confirmation_error = exc
            if not isinstance(exc, Exception):
                cleanup_error = self._abandon_ambiguous_source()
                self._state = "consumed"
                if cleanup_error is not None:
                    _attach_note_best_effort(
                        exc,
                        "ambiguous source cleanup failed",
                    )
                raise
            same_handle_commit = False
        if same_handle_commit:
            return self._lease_confirmed_ambiguous_commit(
                target_name,
                native_error,
            )
        descriptor: int | None = None
        exact_target = False
        probe_error: BaseException | None = None
        try:
            descriptor = self._capability.open_owned_generation_lease(
                target_name
            )
            _verify_descriptor_generation(
                descriptor,
                expected_size=self._required_size,
                expected_sha256=self._required_sha256,
            )
            exact_target = True
        except BaseException as exc:
            probe_error = exc
            if descriptor is not None:
                _close_preserving_primary(descriptor, exc)
                descriptor = None
            if not isinstance(exc, Exception):
                cleanup_error = self._abandon_ambiguous_source()
                self._state = "consumed"
                if cleanup_error is not None:
                    _attach_note_best_effort(
                        exc,
                        "ambiguous source cleanup failed",
                    )
                raise
        cleanup_error = self._abandon_ambiguous_source()
        self._state = "consumed"
        if cleanup_error is not None and not isinstance(
            cleanup_error,
            Exception,
        ):
            if descriptor is not None:
                _close_preserving_primary(descriptor, cleanup_error)
            raise cleanup_error
        if exact_target:
            assert descriptor is not None
            try:
                receipt = self._capability.uncertain_committed_receipt(
                    target_name,
                    native_error,
                )
                if cleanup_error is not None:
                    receipt.diagnostics.append(
                        "ambiguous-source-close:"
                        f"{_safe_exception_type_label(cleanup_error)}"
                    )
            except BaseException as exc:
                _close_preserving_primary(descriptor, exc)
                raise
            return self._committed_lease(descriptor, target_name, receipt)
        receipt = PublishReceipt(
            target_name=target_name,
            status=PublishStatus.OUTCOME_UNKNOWN,
        )
        receipt.diagnostics.append(
            "native-publish:"
            f"{_safe_exception_type_label(native_error)}"
        )
        if probe_error is not None:
            receipt.diagnostics.append(
                "target-probe:"
                f"{_safe_exception_type_label(probe_error)}"
            )
        if confirmation_error is not None:
            receipt.diagnostics.append(
                "same-handle-confirmation:"
                f"{_safe_exception_type_label(confirmation_error)}"
            )
        if cleanup_error is not None:
            receipt.diagnostics.append(
                "ambiguous-source-close:"
                f"{_safe_exception_type_label(cleanup_error)}"
            )
        raise GenerationPublishUncertainError(receipt) from native_error

    def _lease_confirmed_ambiguous_commit(
        self,
        target_name: str,
        native_error: OSError,
    ) -> PublishedLease:
        self._native.confirm_ambiguous_commit()
        try:
            receipt = self._capability.uncertain_committed_receipt(
                target_name,
                native_error,
            )
        except BaseException as exc:
            self._consume_committed_source_preserving(exc)
            raise
        return self._reopen_committed_generation(
            target_name,
            receipt,
            operation="ambiguous-commit-generation-reopen",
        )

    def _reopen_committed_generation(
        self,
        target_name: str,
        receipt: PublishReceipt,
        *,
        operation: str,
    ) -> PublishedLease:
        descriptor: int | None = None
        try:
            source_descriptor = self._native.fileno()
            _verify_descriptor_generation(
                source_descriptor,
                expected_size=self._required_size,
                expected_sha256=self._required_sha256,
            )
            source_identity = _file_object_identity(
                os.fstat(source_descriptor)
            )
            # Windows intentionally denies a second open while the writable
            # source HANDLE is live.  Preserve its file identity, close that
            # authority, then reopen only the published name as read-only.
            self._native.close()
            self._state = "consumed"
            descriptor = self._capability.open_owned_generation_lease(
                target_name
            )
            _verify_descriptor_generation(
                descriptor,
                expected_size=self._required_size,
                expected_sha256=self._required_sha256,
            )
            if _file_object_identity(os.fstat(descriptor)) != source_identity:
                raise GenerationIntegrityError(
                    "published generation is not the exact source file"
                )
        except BaseException as exc:
            self._state = "consumed"
            if descriptor is not None:
                _close_preserving_primary(descriptor, exc)
            self._consume_committed_source_preserving(exc)
            _mark_receipt_uncertain_preserving(
                receipt,
                exc,
                operation=operation,
            )
            if not isinstance(exc, Exception):
                raise
            raise GenerationPublishUncertainError(receipt) from exc
        assert descriptor is not None
        return self._committed_lease(descriptor, target_name, receipt)

    def _committed_lease(
        self,
        descriptor: int,
        target_name: str,
        receipt: PublishReceipt,
    ) -> PublishedLease:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            return self._lease(descriptor, target_name, receipt)
        except BaseException as exc:
            _close_preserving_primary(descriptor, exc)
            _mark_receipt_uncertain_preserving(
                receipt,
                exc,
                operation="published-descriptor-rewind",
            )
            if not isinstance(exc, Exception):
                raise
            raise GenerationPublishUncertainError(receipt) from exc

    def _consume_source_after_publish_control_flow(
        self,
        primary_error: BaseException,
    ) -> None:
        self._state = "consumed"
        if self._native.published:
            self._consume_committed_source_preserving(primary_error)
            return
        if self._native.publish_attempted:
            cleanup_error = self._abandon_ambiguous_source()
            if cleanup_error is not None:
                if isinstance(primary_error, Exception) and not isinstance(
                    cleanup_error,
                    Exception,
                ):
                    raise cleanup_error
                _attach_note_best_effort(
                    primary_error,
                    "ambiguous source cleanup failed",
                )
            return
        self._close_pre_publish_failure(primary_error)

    def _consume_committed_source_preserving(
        self,
        primary_error: BaseException,
    ) -> None:
        self._state = "consumed"
        try:
            self._native.close()
        except BaseException as cleanup_error:
            if isinstance(primary_error, Exception) and not isinstance(
                cleanup_error,
                Exception,
            ):
                raise cleanup_error
            _attach_note_best_effort(
                primary_error,
                "committed source cleanup failed",
            )

    def _discard_known_collision(self) -> BaseException | None:
        try:
            self._native.discard_after_known_no_commit()
        except BaseException as exc:
            return exc
        return None

    def _close_pre_publish_failure(self, primary_error: BaseException) -> None:
        self._state = "consumed"
        try:
            self._native.close()
        except BaseException as cleanup_error:
            if isinstance(primary_error, Exception) and not isinstance(
                cleanup_error,
                Exception,
            ):
                raise cleanup_error
            _attach_note_best_effort(
                primary_error,
                "owned pre-publish source cleanup failed",
            )

    def _discard_known_collision_preserving(
        self,
        primary_error: BaseException,
    ) -> None:
        cleanup_error = self._discard_known_collision()
        if cleanup_error is not None:
            if isinstance(primary_error, Exception) and not isinstance(
                cleanup_error,
                Exception,
            ):
                raise cleanup_error
            _attach_note_best_effort(
                primary_error,
                "owned collision source cleanup failed",
            )

    def _abandon_ambiguous_source(self) -> BaseException | None:
        try:
            self._native.abandon_after_ambiguous_publish()
        except BaseException as exc:
            return exc
        return None

    def _lease(
        self,
        descriptor: int,
        target_name: str,
        receipt: PublishReceipt,
    ) -> PublishedLease:
        return PublishedLease(
            descriptor=descriptor,
            name=target_name,
            size=self._required_size,
            sha256=self._required_sha256,
            receipt=receipt,
        )

    @property
    def _required_size(self) -> int:
        if self._size is None:
            raise OSError("owned generation size is unavailable")
        return self._size

    @property
    def _required_sha256(self) -> str:
        if self._sha256 is None:
            raise OSError("owned generation digest is unavailable")
        return self._sha256


def _verify_descriptor_generation(
    descriptor: int,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or is_link_or_reparse(before):
        raise GenerationIntegrityError(
            "owned generation descriptor is not a regular file"
        )
    if int(before.st_size) != expected_size:
        raise GenerationIntegrityError("owned generation size does not match")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(descriptor, _HASH_CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
        if total > expected_size:
            raise GenerationIntegrityError(
                "owned generation grew during verification"
            )
    after = os.fstat(descriptor)
    if (
        total != expected_size
        or int(after.st_size) != expected_size
        or _descriptor_identity(before) != _descriptor_identity(after)
    ):
        raise GenerationIntegrityError(
            "owned generation changed during verification"
        )
    if digest.hexdigest() != expected_sha256:
        raise GenerationIntegrityError("owned generation digest does not match")


def _descriptor_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(getattr(value, "st_mtime_ns", 0)),
        int(getattr(value, "st_ctime_ns", 0)),
    )


def _file_object_identity(value: os.stat_result) -> tuple[int, int]:
    return (int(value.st_dev), int(value.st_ino))


def _validated_size(value: int) -> int:
    if type(value) is not int or value < 0:
        raise GenerationIntegrityError("expected generation size is invalid")
    return value


def _validated_sha256(value: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise GenerationIntegrityError("expected generation digest is invalid")
    lowered = value.lower()
    if any(character not in "0123456789abcdef" for character in lowered):
        raise GenerationIntegrityError("expected generation digest is invalid")
    return lowered


def _validated_generation_label(value: str) -> str:
    if type(value) is not str:
        raise OSError("content-address label is invalid")
    reserved_stem = value.split(".", 1)[0].rstrip(" .").upper()
    if (
        not value
        or len(value) > _MAX_LABEL_LENGTH
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or ":" in value
        or value.endswith((".", " "))
        or any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or 0xD800 <= ord(character) <= 0xDFFF
            or unicodedata.category(character) == "Cf"
            for character in value
        )
        or any(character in '<>"|?*' for character in value)
        or reserved_stem in _WINDOWS_RESERVED_NAMES
        or (
            len(reserved_stem) == 4
            and reserved_stem[:3] in {"COM", "LPT"}
            and reserved_stem[3] in "123456789"
        )
    ):
        raise OSError("content-address label is invalid")
    return value


def _close_preserving_primary(
    descriptor: int,
    primary_error: BaseException,
) -> None:
    try:
        os.close(descriptor)
    except BaseException:
        _attach_note_best_effort(
            primary_error,
            "published generation probe cleanup failed",
        )


def _mark_receipt_uncertain_preserving(
    receipt: PublishReceipt,
    primary_error: BaseException,
    *,
    operation: str,
) -> None:
    try:
        receipt.mark_authority_uncertain(
            primary_error,
            operation=operation,
        )
    except BaseException as receipt_error:
        if isinstance(primary_error, Exception) and not isinstance(
            receipt_error,
            Exception,
        ):
            raise receipt_error
        _attach_note_best_effort(
            primary_error,
            "publish receipt update failed",
        )


def _attach_note_best_effort(error: BaseException, note: str) -> None:
    try:
        add_note = object.__getattribute__(error, "add_note")
    except BaseException:
        return
    if not callable(add_note):
        return
    try:
        add_note(note)
    except BaseException:
        return


def _safe_exception_type_label(error: BaseException) -> str:
    try:
        value = type.__getattribute__(type(error), "__qualname__")
    except BaseException:
        return "BaseException"
    if type(value) is not str:
        return "BaseException"
    return value


__all__ = [
    "GenerationCollisionError",
    "GenerationError",
    "GenerationIntegrityError",
    "GenerationPublishUncertainError",
    "OwnedGeneration",
    "PublishedLease",
    "PublishReceipt",
    "PublishStatus",
]
