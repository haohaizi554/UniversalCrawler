ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG APT_MIRROR=
ARG APT_SECURITY_MIRROR=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    UCRAWL_HOST=0.0.0.0 \
    UCRAWL_PORT=8000 \
    UCRAWL_NO_QT=1 \
    UCRAWL_NO_BROWSER=1 \
    UCRAWL_USER_DATA_ROOT=/data/user_data \
    UCRAWL_DOWNLOAD_ROOT=/data/downloads

WORKDIR /app

RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && if [ -n "$APT_SECURITY_MIRROR" ]; then \
        sed -i "s|http://security.debian.org/debian-security|$APT_SECURITY_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl tini \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-web.txt ./requirements-web.txt
RUN pip install --upgrade pip \
    && pip install -r requirements-web.txt

ARG INSTALL_PLAYWRIGHT=0
RUN if [ "$INSTALL_PLAYWRIGHT" = "1" ]; then python -m playwright install --with-deps chromium; fi

RUN addgroup --system ucrawl \
    && adduser --system --ingroup ucrawl --home /app --shell /usr/sbin/nologin ucrawl \
    && mkdir -p /data/user_data /data/downloads /ms-playwright

COPY docker/entrypoint.sh /usr/local/bin/ucrawl-entrypoint
RUN chmod +x /usr/local/bin/ucrawl-entrypoint

COPY --chown=ucrawl:ucrawl app ./app
COPY --chown=ucrawl:ucrawl cli ./cli
COPY --chown=ucrawl:ucrawl entry ./entry
COPY --chown=ucrawl:ucrawl ucrawl ./ucrawl
COPY --chown=ucrawl:ucrawl main.py pyproject.toml README.md favicon.ico Web.ico ./

RUN chown -R ucrawl:ucrawl /data /ms-playwright

USER ucrawl

VOLUME ["/data/user_data", "/data/downloads"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/ping || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/ucrawl-entrypoint"]
