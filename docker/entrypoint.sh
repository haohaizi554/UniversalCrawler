#!/bin/sh
set -eu

USER_DATA_ROOT="${UCRAWL_USER_DATA_ROOT:-/data/user_data}"
DOWNLOAD_ROOT="${UCRAWL_DOWNLOAD_ROOT:-/data/downloads}"
HOST="${UCRAWL_HOST:-0.0.0.0}"
PORT="${UCRAWL_PORT:-8000}"

mkdir -p "$USER_DATA_ROOT" "$DOWNLOAD_ROOT"

set -- python -m entry.web_entry --host "$HOST" --port "$PORT"

if [ "${UCRAWL_NO_QT:-1}" != "0" ]; then
    set -- "$@" --no-qt
fi

if [ "${UCRAWL_NO_BROWSER:-1}" != "0" ]; then
    set -- "$@" --no-browser
fi

if [ -n "${UCRAWL_EXTRA_ARGS:-}" ]; then
    # Intentionally relies on shell word splitting so callers can pass
    # multiple flags through a single environment variable.
    # shellcheck disable=SC2086
    set -- "$@" ${UCRAWL_EXTRA_ARGS}
fi

exec "$@"
