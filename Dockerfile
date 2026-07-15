ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ARG PIP_EXTRA_INDEX_URL=
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ARG NO_PROXY=127.0.0.1,localhost

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL} \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    UCRAWL_HOST=0.0.0.0 \
    UCRAWL_PORT=8000 \
    UCRAWL_NO_QT=1 \
    UCRAWL_NO_BROWSER=1 \
    UCRAWL_USER_DATA_ROOT=/data/user_data \
    UCRAWL_DOWNLOAD_ROOT=/data/downloads \
    UCRAWL_TOOL_ROOT=/app/tools

# 用户数据、下载与外部工具位于挂载目录，使可变状态不混入应用层并可跨容器重建保留。
# entrypoint 以 root 启动只为初始化挂载目录和托管证书权限，随后通过 gosu
# 以 ucrawl 用户 exec Web 进程；应用服务不会持续以 root 运行。

WORKDIR /app

RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && if [ -n "$APT_SECURITY_MIRROR" ]; then \
        sed -i "s|http://security.debian.org/debian-security|$APT_SECURITY_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl tini gosu openssl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-web.txt ./requirements-web.txt
RUN pip install --upgrade pip \
    && pip install -r requirements-web.txt

ARG INSTALL_PLAYWRIGHT=0
RUN if [ "$INSTALL_PLAYWRIGHT" = "1" ]; then python -m playwright install --with-deps chromium; fi

RUN addgroup --system ucrawl \
    && adduser --system --ingroup ucrawl --home /app --shell /usr/sbin/nologin ucrawl \
    && mkdir -p /data/user_data /data/downloads /ms-playwright /app/tools

COPY docker/entrypoint.sh /usr/local/bin/ucrawl-entrypoint
RUN chmod +x /usr/local/bin/ucrawl-entrypoint

COPY --chown=ucrawl:ucrawl app ./app
COPY --chown=ucrawl:ucrawl cli ./cli
COPY --chown=ucrawl:ucrawl entry ./entry
# shared 与 UI 分别承载动态导入协议和运行时资源，必须随生产入口一并复制。
COPY --chown=ucrawl:ucrawl shared ./shared
COPY --chown=ucrawl:ucrawl ucrawl ./ucrawl
COPY --chown=ucrawl:ucrawl UI ./UI
COPY --chown=ucrawl:ucrawl main.py pyproject.toml README.md favicon.ico Web.ico ./

RUN chown -R ucrawl:ucrawl /data /ms-playwright /app/tools

VOLUME ["/data/user_data", "/data/downloads", "/app/tools"]
EXPOSE 8000

# ``curl -k`` 仅用于容器内 loopback 健康检查，以接受 entrypoint 生成的本地
# 自签名证书；它不会放宽外部客户端或应用请求的 TLS 验证。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fkSs https://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/ucrawl-entrypoint"]
