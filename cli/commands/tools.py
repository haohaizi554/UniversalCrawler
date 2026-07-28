"""Thin ``ucrawl tools`` command adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from collections.abc import Mapping
from typing import Any

from cli.exit_codes import CliExitCode, exit_code_for_status
from shared.execution_profile import (
    DEFAULT_LOCAL_TOOL_PERMISSIONS,
    ExecutionProfile,
    local_execution_profile,
)
from shared.runtime_options import get_default_save_dir
from ucrawl.tools import ToolRunnerUnavailableError, ToolsAPI


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="indent JSON output",
    )


def _add_params_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--params",
        default="{}",
        metavar="JSON",
        help="tool parameters as a JSON object",
    )


def add_tools_arguments(parser: argparse.ArgumentParser) -> None:
    """Register list/describe/validate/run/cancel/history subcommands."""

    subparsers = parser.add_subparsers(
        dest="tools_command",
        title="tool operations",
        required=True,
    )

    list_parser = subparsers.add_parser("list", help="list available tools")
    _add_output_arguments(list_parser)

    describe_parser = subparsers.add_parser("describe", help="describe one tool")
    describe_parser.add_argument("tool_id")
    _add_output_arguments(describe_parser)

    validate_parser = subparsers.add_parser(
        "validate",
        help="validate parameters without running a tool",
    )
    validate_parser.add_argument("tool_id")
    _add_params_argument(validate_parser)
    _add_output_arguments(validate_parser)

    run_parser = subparsers.add_parser("run", help="start a tool run")
    run_parser.add_argument("tool_id")
    _add_params_argument(run_parser)
    _add_output_arguments(run_parser)

    cancel_parser = subparsers.add_parser("cancel", help="cancel a tool run")
    cancel_parser.add_argument("run_id")
    _add_output_arguments(cancel_parser)

    history_parser = subparsers.add_parser("history", help="show tool run history")
    history_parser.add_argument("--tool-id")
    history_parser.add_argument("--status")
    history_parser.add_argument("--limit", type=int)
    _add_output_arguments(history_parser)


def _parse_params(raw_params: str) -> dict[str, Any]:
    try:
        params = json.loads(raw_params)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--params must be valid JSON: {exc.msg}") from exc
    if not isinstance(params, dict):
        raise ValueError("--params must be a JSON object")
    return params


def _execute(api: ToolsAPI, args: argparse.Namespace, params: dict[str, Any] | None) -> Any:
    operation = args.tools_command
    if operation == "list":
        return api.list()
    if operation == "describe":
        return api.describe(args.tool_id)
    if operation == "validate":
        return api.validate(args.tool_id, params or {})
    if operation == "run":
        return api.run(args.tool_id, params or {})
    if operation == "cancel":
        return api.cancel(args.run_id)
    if operation == "history":
        filters = {
            key: value
            for key, value in (
                ("tool_id", args.tool_id),
                ("status", args.status),
                ("limit", args.limit),
            )
            if value is not None
        }
        return api.history(**filters)
    raise ValueError(f"unknown tools operation: {operation}")


def _cli_tool_execution_profile() -> ExecutionProfile:
    download_root = Path(get_default_save_dir()).expanduser().resolve()
    return local_execution_profile(
        host_surface="cli",
        owner_id="cli:local",
        approved_roots=(download_root,),
        tool_permissions=DEFAULT_LOCAL_TOOL_PERMISSIONS,
        allow_external_plugins=False,
    )


def _write_secondary_diagnostic(message: str) -> None:
    """Write a secondary diagnostic without replacing process control flow."""
    try:
        sys.stderr.write(message)
    except Exception:
        pass


def _wait_for_run(api: ToolsAPI, queued: Any) -> tuple[Any, bool]:
    if not isinstance(queued, Mapping) or queued.get("status") != "queued":
        return queued, False
    run_id = queued.get("run_id")
    if type(run_id) is not str or not run_id.strip():
        return {
            "status": "error",
            "code": "tool_protocol_error",
            "message": (
                "tool runner returned a queued result without a valid run_id"
            ),
        }, False
    try:
        return api.wait_for_run(run_id, timeout=None), False
    except KeyboardInterrupt:
        cancelled: Any = {"status": "cancelled", "run_id": run_id}
        try:
            api.cancel(run_id)
        except Exception:
            _write_secondary_diagnostic("tool cancellation request failed\n")
        try:
            terminal = api.wait_for_run(run_id, timeout=1.0)
        except Exception:
            _write_secondary_diagnostic("tool cancellation wait failed\n")
            terminal = cancelled
        return terminal, True


def _attach_cleanup_failure(
    primary_error: BaseException,
    cleanup_error: BaseException,
) -> None:
    note = _describe_cleanup_failure(cleanup_error)
    try:
        add_note = getattr(primary_error, "add_note", None)
    except BaseException:
        add_note = None
    if callable(add_note):
        try:
            add_note(note)
            return
        except BaseException:
            pass
    try:
        setattr(primary_error, "_tools_cleanup_error", cleanup_error)
    except BaseException:
        pass


def _describe_cleanup_failure(cleanup_error: BaseException) -> str:
    """Return a cleanup diagnostic even for hostile exception objects."""
    try:
        detail = str(cleanup_error)
    except BaseException:
        detail = ""
    if type(detail) is str and detail:
        return "tool runner cleanup failed: " + detail
    try:
        error_name = type(cleanup_error).__name__
    except BaseException:
        error_name = "unknown error"
    if type(error_name) is not str or not error_name:
        error_name = "unknown error"
    return "tool runner cleanup failed with " + error_name


def _describe_operation_failure(operation_error: BaseException) -> str:
    """Return an unavailable-operation diagnostic without trusting metadata."""
    try:
        detail = str(operation_error)
    except BaseException:
        detail = ""
    if type(detail) is str and detail:
        return detail
    try:
        error_name = type(operation_error).__name__
    except BaseException:
        error_name = "unknown error"
    if type(error_name) is not str or not error_name:
        error_name = "unknown error"
    return "tool runner operation failed with " + error_name


def handle_tools_command(args: argparse.Namespace) -> int:
    params = None
    if args.tools_command in {"validate", "run"}:
        try:
            params = _parse_params(args.params)
        except ValueError as exc:
            sys.stderr.write(f"{exc}\n")
            return int(CliExitCode.USAGE)

    if args.tools_command == "cancel":
        sys.stderr.write(
            "standalone cancellation is process-scoped; cancel from the "
            "process that started the run\n"
        )
        return int(CliExitCode.USAGE)

    api = None
    result: Any = None
    operation_error: BaseException | None = None
    unexpected_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    cleanup_control_error: KeyboardInterrupt | SystemExit | None = None
    interrupted = False
    try:
        api = ToolsAPI(execution_profile=_cli_tool_execution_profile())
        result = _execute(api, args, params)
        if args.tools_command == "run":
            result, interrupted = _wait_for_run(api, result)
    except ToolRunnerUnavailableError as exc:
        operation_error = exc
    except BaseException as exc:
        unexpected_error = exc
    finally:
        if api is not None:
            try:
                if api.close() is not True:
                    cleanup_error = RuntimeError(
                        "tool runner cleanup did not complete"
                    )
            except (KeyboardInterrupt, SystemExit) as exc:
                cleanup_control_error = exc
            except BaseException as exc:
                cleanup_error = exc

    if unexpected_error is not None:
        cleanup_failure = cleanup_control_error or cleanup_error
        if cleanup_failure is not None:
            _attach_cleanup_failure(unexpected_error, cleanup_failure)
        raise unexpected_error
    if operation_error is not None:
        _write_secondary_diagnostic(
            _describe_operation_failure(operation_error) + "\n"
        )
        cleanup_failure = cleanup_control_error or cleanup_error
        if cleanup_failure is not None:
            _write_secondary_diagnostic(
                _describe_cleanup_failure(cleanup_failure) + "\n"
            )
        return int(CliExitCode.ERROR)
    if cleanup_control_error is not None:
        raise cleanup_control_error

    indent = 2 if getattr(args, "pretty", False) else None
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=indent) + "\n")

    if cleanup_error is not None:
        _write_secondary_diagnostic(_describe_cleanup_failure(cleanup_error) + "\n")
    if interrupted:
        return 130
    if cleanup_error is not None:
        return int(CliExitCode.ERROR)

    if isinstance(result, Mapping) and "status" in result:
        return int(exit_code_for_status(str(result["status"])))
    return int(CliExitCode.OK)
