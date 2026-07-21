"""HTTP REST 路由装配。"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.exceptions import ConfigValidationError
from app.services import update_check_service
from app.services.secure_updater import record_skipped_update
from app.web.api_result import error_result, finalize_api_result
from app.web.controller_config_service import WebControllerConfigService
from app.web.controller_route_service import require_valid_video_id
from app.web.session_runtime import is_local_host
from shared.release_identity import ReleaseIdentity, load_runtime_release_identity


def _finalize_route_result(payload: Any, *, enforce_statuses: set[int] | None = None) -> Any:
    """除明确的安全边界外，保留旧接口以 200 返回错误正文的约定。"""
    if not isinstance(payload, dict) or not (payload.get("status") == "error" or "error" in payload):
        return payload
    status_code = int(payload.get("http_status", 400))
    if status_code in (enforce_statuses or set()):
        return finalize_api_result(payload)
    body = dict(payload)
    body.pop("http_status", None)
    return body

class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="allow")

class ConfigUpdatesRequest(RootModel[dict[str, dict[str, Any]]]):
    pass

class FrontendActionRequest(_RequestModel):
    action: str = Field(..., min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    frontend_version: int | None = Field(default=0, ge=0)
    request_id: str = Field(default="", max_length=80)

class UpdateCheckRequest(_RequestModel):
    local_version: str = Field(default="", max_length=40)

class UpdatePrepareRequest(UpdateCheckRequest):
    selected_version: str = Field(default="", max_length=40)
    selected_candidate_id: str = Field(default="", max_length=80)
    confirm_revision_change: bool = False

class UpdateSkipRequest(UpdatePrepareRequest):
    pass

class UpdateInstallRequest(_RequestModel):
    pass


def _public_update_result(result: Any) -> dict[str, Any]:
    """公开版本元数据，但不泄露服务端校验路径。"""
    payload = asdict(result)
    payload["local_tag"] = result.local_identity.tag
    payload["latest_tag"] = result.selected_identity.tag
    payload["selected_candidate_id"] = result.selected_identity.candidate_id
    payload.pop("manifest_path", None)
    payload.pop("signature_path", None)
    for candidate in payload.get("candidates", []):
        if isinstance(candidate, dict):
            candidate.pop("manifest_path", None)
            candidate.pop("signature_path", None)
    for candidate, public_candidate in zip(result.candidates, payload.get("candidates", []), strict=False):
        public_candidate["candidate_id"] = candidate.candidate_id
        public_candidate["display_label"] = candidate.display_label
    return payload


def _check_secure_update_for_runtime() -> Any:
    """读取受信运行时身份；r0 保持旧调用形状，兼容现有扩展和测试替身。"""

    identity = load_runtime_release_identity()
    if identity.revision:
        return update_check_service.check_secure_update(
            identity.version,
            local_revision=identity.revision,
        )
    return update_check_service.check_secure_update(identity.version)


def _select_update_result(result: Any, *, candidate_id: str = "", version: str = "") -> Any:
    """集中处理新 candidate id 与旧 version 请求，避免 prepare/skip 选择规则漂移。"""

    selected_candidate_id = str(candidate_id or "").strip()
    if selected_candidate_id:
        return result.for_candidate(selected_candidate_id)
    selected_version = str(version or "").strip()
    if selected_version:
        return result.for_version(selected_version)
    return result.for_candidate(result.candidates[0].candidate_id)


async def _run_controller_worker_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.get_running_loop().run_in_executor(None, partial(func, *args, **kwargs))

def build_rest_router(
    *,
    get_request_context: Callable[[Request], Any],
    search_service,
    workflow_route_service,
    controller_route_service,
    directory_service,
    file_response_service,
) -> APIRouter:

    router = APIRouter()

    @router.get("/healthz", include_in_schema=False)
    async def healthcheck():
        return {"status": "ok"}

    @router.get("/api/ping")
    async def ping():
        from cli import __version__

        return {"status": "ok", "version": __version__}

    @router.get("/api/session/bootstrap")
    async def bootstrap_session(request: Request):
        context = get_request_context(request)
        return {"status": "ok", "session_id": context.session_id}

    @router.get("/api/platforms")
    async def get_platforms(request: Request):
        return await _run_controller_worker_call(get_request_context(request).controller.get_platforms)

    @router.get("/api/config")
    async def get_config(request: Request):
        return await _run_controller_worker_call(get_request_context(request).controller.get_config)

    @router.put("/api/config")
    async def update_config(request: Request, updates: ConfigUpdatesRequest):
        context = get_request_context(request)
        controller = context.controller
        approved_roots = context.approved_roots_snapshot()
        handler = getattr(controller, "async_update_config", None)
        if callable(handler):
            errors = await handler(updates.root, approved_roots)
        else:
            errors = await _run_controller_worker_call(controller.update_config, updates.root, approved_roots)
        if errors:
            joined = "; ".join(f"{error.section}.{error.key}: {error.error}" for error in errors)
            return _finalize_route_result(error_result(joined, http_status=400), enforce_statuses={400})
        return {"status": "ok"}

    @router.get("/api/state")
    async def get_state(request: Request):
        return await _run_controller_worker_call(get_request_context(request).controller.get_state)

    @router.get("/api/frontend/state")
    async def get_frontend_state(request: Request):
        controller = get_request_context(request).controller
        getter = getattr(controller, "get_frontend_state", None)
        if callable(getter):
            return await _run_controller_worker_call(getter)
        return {"status": "error", "message": "frontend state is unavailable"}

    @router.get("/api/frontend/delta")
    async def get_frontend_delta(request: Request, since_version: int = Query(default=0, ge=0)):
        controller = get_request_context(request).controller
        getter = getattr(controller, "get_frontend_delta", None)
        if callable(getter):
            return await _run_controller_worker_call(getter, since_version)
        snapshot_getter = getattr(controller, "get_frontend_state", None)
        if callable(snapshot_getter):
            sections = await _run_controller_worker_call(snapshot_getter)
            return {"version": 0, "base_version": since_version, "full": True, "sections": sections}
        return {"status": "error", "message": "frontend delta is unavailable"}

    @router.get("/api/frontend/icons")
    async def get_frontend_icons(request: Request):
        controller = get_request_context(request).controller
        getter = getattr(controller, "get_frontend_icons", None)
        if callable(getter):
            return getter()
        return {"status": "error", "message": "frontend icons are unavailable"}

    @router.get("/api/i18n/{language}")
    async def get_i18n_catalog(language: str):
        from shared.localization import SUPPORTED_LANGUAGES, TRANSLATIONS

        normalized = str(language or "").strip()
        if normalized not in SUPPORTED_LANGUAGES or normalized == "zh-CN":
            return {}
        return TRANSLATIONS.get(normalized, {})

    @router.post("/api/frontend/action")
    async def frontend_action(request: Request, body: FrontendActionRequest):
        context = get_request_context(request)
        controller = context.controller
        approved_roots = context.approved_roots_snapshot()
        try:
            payload = WebControllerConfigService.authorize_frontend_action_payload(
                body.action,
                body.payload,
                approved_roots,
            )
        except (ConfigValidationError, PermissionError, ValueError) as exc:
            is_directory_error = isinstance(exc, PermissionError)
            is_value_error = isinstance(exc, ValueError)
            error_payload = {
                "status": "error",
                "message": str(exc),
                "http_status": 403 if is_directory_error else 400,
                "data": {
                    "code": (
                        "directory_not_authorized"
                        if is_directory_error
                        else "invalid_config_value"
                        if is_value_error
                        else "config_not_allowed"
                    )
                },
            }
            if body.request_id:
                error_payload["request_id"] = body.request_id
            return _finalize_route_result(
                error_payload,
                enforce_statuses={400, 403},
            )
        handler = getattr(controller, "async_handle_frontend_action", None)
        handler_accepts_roots = callable(handler) and WebControllerConfigService.handler_accepts_approved_roots(handler)
        if not handler_accepts_roots:
            fallback = getattr(controller, "handle_frontend_action", None)
            if not callable(handler):
                handler = fallback
                handler_accepts_roots = callable(handler) and WebControllerConfigService.handler_accepts_approved_roots(
                    handler
                )
        try:
            frontend_version = int(body.frontend_version or 0)
        except (TypeError, ValueError):
            frontend_version = 0
        if callable(handler):
            if inspect.iscoroutinefunction(handler):
                result = (
                    await handler(body.action, payload, approved_roots=approved_roots)
                    if handler_accepts_roots
                    else await handler(body.action, payload)
                )
            else:
                result = await _run_controller_worker_call(
                    handler,
                    body.action,
                    payload,
                    **({"approved_roots": approved_roots} if handler_accepts_roots else {}),
                )
                if inspect.isawaitable(result):
                    result = await result
            if isinstance(result, dict):
                result = dict(result)
                if body.request_id:
                    result["request_id"] = body.request_id
                delta_getter = getattr(controller, "get_frontend_delta", None)
                if callable(delta_getter):
                    try:
                        delta = await _run_controller_worker_call(delta_getter, frontend_version)
                    except Exception:
                        delta = None
                    if isinstance(delta, dict):
                        result["frontend_delta"] = delta
            return _finalize_route_result(result, enforce_statuses={403})
        return _finalize_route_result(error_result("frontend action is unavailable", http_status=501))

    @router.post("/api/update/check")
    async def check_update(request: Request, _body: UpdateCheckRequest):
        try:
            result = await _run_controller_worker_call(_check_secure_update_for_runtime)
        except Exception as exc:
            return _finalize_route_result(
                error_result(str(exc) or "update check failed", http_status=502, error_key="message"),
                enforce_statuses={502},
            )
        payload = _public_update_result(result)
        client = getattr(request, "client", None)
        payload["can_prepare"] = bool(
            is_local_host(getattr(client, "host", None))
            and result.status == update_check_service.UPDATE_STATUS_AVAILABLE
            and result.candidates
        )
        return payload

    @router.post("/api/update/prepare")
    async def prepare_update(request: Request, body: UpdatePrepareRequest):
        client = getattr(request, "client", None)
        if not is_local_host(getattr(client, "host", None)):
            return _finalize_route_result(
                error_result("update preparation is available only on this device", http_status=403, error_key="message"),
                enforce_statuses={403},
            )
        context = get_request_context(request)
        context.clear_prepared_update()
        try:
            result = await _run_controller_worker_call(_check_secure_update_for_runtime)
            if result.status != update_check_service.UPDATE_STATUS_AVAILABLE or not result.candidates:
                return _finalize_route_result(
                    error_result(
                        "no verified update candidate is available",
                        http_status=409,
                        error_key="message",
                    ),
                    enforce_statuses={409},
                )
            try:
                selected_result = _select_update_result(
                    result,
                    candidate_id=body.selected_candidate_id,
                    version=body.selected_version,
                )
            except ValueError as exc:
                return _finalize_route_result(
                    error_result(str(exc), http_status=400, error_key="message"),
                    enforce_statuses={400},
                )
            if (
                selected_result.selected_identity <= selected_result.local_identity
                and not body.confirm_revision_change
            ):
                action = "reinstall" if selected_result.selected_identity == selected_result.local_identity else "downgrade"
                return _finalize_route_result(
                    error_result(
                        "explicit confirmation is required for revision reinstall or downgrade",
                        http_status=409,
                        error_key="message",
                        confirmation_required=True,
                        confirmation_action=action,
                        candidate_id=selected_result.selected_identity.candidate_id,
                    ),
                    enforce_statuses={409},
                )
            prepare_kwargs = {}
            if selected_result.selected_identity <= selected_result.local_identity:
                prepare_kwargs["allow_downgrade"] = True
            prepared = await _run_controller_worker_call(
                update_check_service.prepare_verified_update,
                selected_result,
                **prepare_kwargs,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return _finalize_route_result(
                error_result(str(exc) or "update preparation failed", http_status=502, error_key="message"),
                enforce_statuses={502},
            )
        context.store_prepared_update(prepared)
        return {
            "status": "ready",
            "version": prepared.version,
            "release_revision": prepared.release_revision,
            "candidate_id": ReleaseIdentity(prepared.version, prepared.release_revision).candidate_id,
            "installer_name": Path(prepared.installer_path).name,
        }

    @router.post("/api/update/skip")
    async def skip_update(request: Request, body: UpdateSkipRequest):
        client = getattr(request, "client", None)
        if not is_local_host(getattr(client, "host", None)):
            return _finalize_route_result(
                error_result("update skip is available only on this device", http_status=403, error_key="message"),
                enforce_statuses={403},
            )
        try:
            result = await _run_controller_worker_call(_check_secure_update_for_runtime)
            if not result.candidates:
                raise ValueError("no verified update candidate is available")
            selected_result = _select_update_result(
                result,
                candidate_id=body.selected_candidate_id,
                version=body.selected_version,
            )
            await _run_controller_worker_call(
                record_skipped_update,
                selected_result.latest_version,
                release_revision=selected_result.latest_revision,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return _finalize_route_result(
                error_result(str(exc) or "update skip failed", http_status=400, error_key="message"),
                enforce_statuses={400},
            )
        return {
            "status": "skipped",
            "version": selected_result.latest_version,
            "release_revision": selected_result.latest_revision,
            "candidate_id": selected_result.selected_identity.candidate_id,
        }

    @router.post("/api/update/install")
    async def install_update(request: Request, _body: UpdateInstallRequest):
        client = getattr(request, "client", None)
        if not is_local_host(getattr(client, "host", None)):
            return _finalize_route_result(
                error_result("update installation is available only on this device", http_status=403, error_key="message"),
                enforce_statuses={403},
            )
        restart_argv = list(getattr(request.app.state, "web_restart_argv", []) or [])
        shutdown_callback = getattr(request.app.state, "web_shutdown_callback", None)
        if not restart_argv or not callable(shutdown_callback):
            return _finalize_route_result(
                error_result("web update restart handoff is unavailable", http_status=503, error_key="message"),
                enforce_statuses={503},
            )
        context = get_request_context(request)
        prepared = context.take_prepared_update()
        if prepared is None:
            return _finalize_route_result(
                error_result("no verified update package is ready", http_status=409, error_key="message"),
                enforce_statuses={409},
            )
        try:
            await _run_controller_worker_call(
                update_check_service.launch_prepared_update,
                prepared,
                restart_argv=restart_argv,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            context.store_prepared_update(prepared)
            return _finalize_route_result(
                error_result(str(exc) or "update installer launch failed", http_status=500, error_key="message"),
                enforce_statuses={500},
            )
        shutdown_callback()
        return {
            "status": "installing",
            "version": prepared.version,
            "release_revision": prepared.release_revision,
            "candidate_id": ReleaseIdentity(prepared.version, prepared.release_revision).candidate_id,
        }

    @router.post("/api/scan")
    async def scan_directory(request: Request, body: dict):
        result = await directory_service.scan_directory(request, body)
        return _finalize_route_result(result, enforce_statuses={403})

    @router.post("/api/search")
    async def search(request: Request, body: dict):
        return _finalize_route_result(await search_service.search(request, body))

    @router.post("/api/crawl/start")
    async def start_crawl(request: Request, body: dict):
        return _finalize_route_result(await workflow_route_service.start_crawl(request, body))

    @router.post("/api/crawl/stop")
    async def stop_crawl(request: Request):
        return _finalize_route_result(await workflow_route_service.stop_crawl(request))

    @router.post("/api/crawl/select")
    async def select_tasks(request: Request, body: dict):
        return _finalize_route_result(await workflow_route_service.select_tasks(request, body))

    @router.post("/api/debug/trigger-select")
    async def debug_trigger_select(request: Request):
        result = await controller_route_service.trigger_select(request)
        return _finalize_route_result(result, enforce_statuses={404})

    @router.delete("/api/video/{video_id}")
    async def delete_video(request: Request, video_id: str):
        result = await controller_route_service.delete_video(request, video_id)
        return _finalize_route_result(result, enforce_statuses={400, 403})

    @router.post("/api/video/rename")
    async def rename_video(request: Request, body: dict):
        result = await controller_route_service.rename_video(request, body)
        if not isinstance(body.get("video_id"), str) or not isinstance(body.get("new_title"), str):
            return _finalize_route_result(result)
        if not body.get("video_id"):
            return _finalize_route_result(result)
        return _finalize_route_result(result, enforce_statuses={400, 403})

    @router.post("/api/download")
    async def download_video(request: Request, body: dict):
        return _finalize_route_result(await workflow_route_service.direct_download(request, body))

    @router.get("/api/media/{video_id}")
    async def get_media(request: Request, video_id: str, range_header: str | None = Header(default=None, alias="Range")):
        require_valid_video_id(video_id)
        return await file_response_service.get_media(request, video_id, range_header)

    @router.get("/api/dir/list")
    async def list_directory(request: Request, path: str = ""):
        result = await directory_service.list_directory(request, path)
        return _finalize_route_result(result, enforce_statuses={403})

    @router.post("/api/dir/change")
    async def change_dir(request: Request):
        result = await directory_service.change_dir(request)
        return _finalize_route_result(result, enforce_statuses={403})

    @router.post("/api/dir/pick-native")
    async def pick_native_folder(request: Request):
        return _finalize_route_result(
            await directory_service.pick_native_folder(request),
            enforce_statuses={403},
        )

    @router.get("/api/debug/latest-log")
    async def download_latest_log(request: Request):
        return await file_response_service.async_latest_log_response(request)

    @router.get("/api/debug/error-summary")
    async def download_error_summary(request: Request):
        return await file_response_service.async_latest_error_summary_response(request)

    return router
