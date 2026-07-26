"""Thin ``ucrawl tools`` command adapter."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from typing import Any

from cli.exit_codes import CliExitCode, exit_code_for_status
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


def handle_tools_command(args: argparse.Namespace) -> int:
    params = None
    if args.tools_command in {"validate", "run"}:
        try:
            params = _parse_params(args.params)
        except ValueError as exc:
            sys.stderr.write(f"{exc}\n")
            return int(CliExitCode.USAGE)

    try:
        result = _execute(ToolsAPI(), args, params)
    except ToolRunnerUnavailableError as exc:
        sys.stderr.write(f"{exc}\n")
        return int(CliExitCode.ERROR)

    indent = 2 if getattr(args, "pretty", False) else None
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=indent) + "\n")

    if isinstance(result, Mapping) and "status" in result:
        return int(exit_code_for_status(str(result["status"])))
    return int(CliExitCode.OK)
