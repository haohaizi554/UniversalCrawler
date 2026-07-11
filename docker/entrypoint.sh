#!/bin/sh
set -eu

USER_DATA_ROOT="${UCRAWL_USER_DATA_ROOT:-/data/user_data}"
DOWNLOAD_ROOT="${UCRAWL_DOWNLOAD_ROOT:-/data/downloads}"
TOOL_ROOT="${UCRAWL_TOOL_ROOT:-/app/tools}"
HOST="${UCRAWL_HOST:-0.0.0.0}"
PORT="${UCRAWL_PORT:-8000}"
TLS_DIR="${UCRAWL_TLS_DIR:-$USER_DATA_ROOT/tls}"
CUSTOM_SSL_CERTFILE="${UCRAWL_SSL_CERTFILE:-}"
CUSTOM_SSL_KEYFILE="${UCRAWL_SSL_KEYFILE:-}"
MANAGED_TLS=1

if [ -n "$CUSTOM_SSL_CERTFILE" ] || [ -n "$CUSTOM_SSL_KEYFILE" ]; then
    if [ -z "$CUSTOM_SSL_CERTFILE" ] || [ -z "$CUSTOM_SSL_KEYFILE" ]; then
        echo "error: UCRAWL_SSL_CERTFILE and UCRAWL_SSL_KEYFILE must be configured together" >&2
        exit 2
    fi
    SSL_CERTFILE="$CUSTOM_SSL_CERTFILE"
    SSL_KEYFILE="$CUSTOM_SSL_KEYFILE"
    MANAGED_TLS=0
    if [ ! -f "$SSL_CERTFILE" ] || [ ! -f "$SSL_KEYFILE" ]; then
        echo "error: custom TLS certificate or key does not exist" >&2
        exit 2
    fi
else
    SSL_CERTFILE="$TLS_DIR/web-cert.pem"
    SSL_KEYFILE="$TLS_DIR/web-key.pem"
fi

mkdir -p "$USER_DATA_ROOT" "$DOWNLOAD_ROOT" "$TOOL_ROOT" "$TLS_DIR"

# A non-loopback listener is rejected without TLS. Generate a persistent local
# certificate when the operator has not mounted a trusted certificate pair.
if [ "$MANAGED_TLS" = "1" ] && { [ ! -f "$SSL_CERTFILE" ] || [ ! -f "$SSL_KEYFILE" ]; }; then
    cert_tmp="$SSL_CERTFILE.tmp.$$"
    key_tmp="$SSL_KEYFILE.tmp.$$"
    rm -f "$cert_tmp" "$key_tmp"
    umask 077
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 825 \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -keyout "$key_tmp" -out "$cert_tmp" >/dev/null 2>&1
    mv -f "$key_tmp" "$SSL_KEYFILE"
    mv -f "$cert_tmp" "$SSL_CERTFILE"
fi

if [ "$(id -u)" = "0" ]; then
    chown ucrawl:ucrawl "$USER_DATA_ROOT" "$DOWNLOAD_ROOT" "$TOOL_ROOT" 2>/dev/null || true
    chmod 0775 "$USER_DATA_ROOT" "$DOWNLOAD_ROOT" "$TOOL_ROOT" 2>/dev/null || true
    if [ "$MANAGED_TLS" = "1" ]; then
        chown ucrawl:ucrawl "$TLS_DIR" "$SSL_CERTFILE" "$SSL_KEYFILE" 2>/dev/null || true
    fi
fi
if [ "$MANAGED_TLS" = "1" ]; then
    chmod 0600 "$SSL_KEYFILE" 2>/dev/null || true
    chmod 0644 "$SSL_CERTFILE" 2>/dev/null || true
fi

set -- python -m entry.web_entry --host "$HOST" --port "$PORT" \
    --ssl-certfile "$SSL_CERTFILE" --ssl-keyfile "$SSL_KEYFILE"

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

if [ "$(id -u)" = "0" ]; then
    exec gosu ucrawl "$@"
fi

exec "$@"
