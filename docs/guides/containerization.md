# 容器化部署说明

## 目标

当前项目的容器化支持聚焦在 `Web/API` 运行形态，不覆盖桌面 GUI 交付。

推荐容器入口：

- `entry.web_entry`
- `--no-qt`
- `--no-browser`

容器内最终等价于：

```bash
python -m entry.web_entry --host 0.0.0.0 --port 8000 --no-qt --no-browser \
  --ssl-certfile /data/user_data/tls/web-cert.pem \
  --ssl-keyfile /data/user_data/tls/web-key.pem
```

入口脚本会在首次启动时生成并持久化本地 TLS 证书与 Web 访问口令；生产或局域网部署建议通过环境变量成对挂载受信任证书并设置固定高熵口令。只配置证书或私钥之一、或自定义文件不存在时，容器会直接拒绝启动，避免覆盖操作员提供的证书。

## 为什么只支持 Web/API 容器

当前项目存在两个明确的运行时边界：

### 1. GUI 不适合作为标准容器交付

- 桌面 GUI 基于 `PyQt6`
- 任务栏、系统托盘、窗口图标、原生目录选择框都偏本机桌面环境
- 这类能力适合 Windows 本地运行，不适合作为标准容器形态交付

### 2. 下载链存在跨平台差异

- `ffmpeg` 已支持项目内文件与系统 `PATH` fallback，Linux 容器可用
- `N_m3u8DL-RE` 现已支持按运行平台自动识别：
  - Windows 优先查找 `N_m3u8DL-RE.exe`
  - Linux 容器优先查找 `N_m3u8DL-RE` / `n-m3u8dl-re`
  - 若项目内未提供文件，则回退到系统 `PATH`

因此当前容器支持矩阵应明确为：

- 支持：Web UI / REST API / WebSocket / 基于 `ffmpeg` 的下载链
- 条件支持：依赖 Playwright 的平台抓取能力，需要在构建时显式安装浏览器
- 条件支持：依赖 `N_m3u8DL-RE` 的完整 HLS 下载能力，需要在容器中提供 Linux 可执行文件或 PATH 命令
- 不支持：桌面 GUI / 系统托盘 / Qt 交互

## 当前容器资产

- [Dockerfile](../../Dockerfile)
- [.dockerignore](../../.dockerignore)
- [docker-compose.yml](../../docker-compose.yml)
- [requirements-web.txt](../../requirements-web.txt)
- [docker/entrypoint.sh](../../docker/entrypoint.sh)
- [.env.docker.example](../../.env.docker.example)

## 工程化约束

当前容器实现新增了以下约束：

- 镜像使用 `requirements-web.txt`，明确排除 `PyQt6` 和测试类依赖
- 镜像以非 root 用户 `ucrawl` 运行
- 启动通过 `tini + docker/entrypoint.sh` 收口，统一解析容器环境变量
- Docker 构建默认使用更适合中国大陆网络的 Debian / PyPI 镜像源，仍可通过环境变量覆盖
- 数据目录通过卷挂载写入 `/data/user_data` 和 `/data/downloads`
- 外部工具目录统一挂载到 `/app/tools`，通过 `UCRAWL_TOOL_ROOT` 收口
- Compose 与镜像都内置无状态 `/healthz` 健康检查
- 非回环监听强制使用 HTTPS；Compose 默认只把端口发布到宿主机 `127.0.0.1`
- 远程 Web/API 与 WebSocket 在普通 session 之外还需要应用访问口令

## 运行时环境变量

容器支持以下关键环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `UCRAWL_HOST` | `0.0.0.0` | Web 服务监听地址 |
| `UCRAWL_PORT` | `8000` | 容器内部监听端口 |
| `UCRAWL_BIND_IP` | `127.0.0.1` | Compose 在宿主机发布端口的地址；局域网部署可显式改为 `0.0.0.0` |
| `UCRAWL_NO_QT` | `1` | 容器内默认关闭 Qt |
| `UCRAWL_NO_BROWSER` | `1` | 容器内默认不自动拉起浏览器 |
| `UCRAWL_USER_DATA_ROOT` | `/data/user_data` | 用户数据目录 |
| `UCRAWL_DOWNLOAD_ROOT` | `/data/downloads` | 下载目录 |
| `UCRAWL_TOOL_ROOT` | `/app/tools` | 外部工具目录，可挂载 Linux 版 `N_m3u8DL-RE` |
| `UCRAWL_SSL_CERTFILE` / `UCRAWL_SSL_KEYFILE` | 自动生成 | 自定义 TLS 证书与私钥路径，必须成对提供 |
| `UCRAWL_WEB_ACCESS_TOKEN` | 自动生成 | 固定 Web 访问口令；留空时从持久化文件读取或首次生成 |
| `UCRAWL_WEB_ACCESS_TOKEN_FILE` | `/data/user_data/web-access-token` | 自动访问口令的持久化路径 |
| `UCRAWL_EXTRA_ARGS` | 空 | 透传额外启动参数 |
| `UCRAWL_APT_MIRROR` | 清华 Debian 源 | Docker build 使用的 Debian 镜像 |
| `UCRAWL_APT_SECURITY_MIRROR` | 清华 Debian Security 源 | Docker build 使用的安全更新镜像 |
| `UCRAWL_PIP_INDEX_URL` | 清华 PyPI 源 | Docker build 使用的 Python 包索引 |
| `UCRAWL_PIP_TRUSTED_HOST` | `pypi.tuna.tsinghua.edu.cn` | 与 `UCRAWL_PIP_INDEX_URL` 配套 |
| `UCRAWL_HTTP_PROXY` / `UCRAWL_HTTPS_PROXY` | 空 | 公司网络或代理环境下的构建 / 运行代理 |
| `UCRAWL_NO_PROXY` | `127.0.0.1,localhost` | 直连白名单 |

为了便于 Compose 本地化配置，仓库还提供：

- `.env.docker.example`

可复制为本地 `.env` 后再启动：

```bash
cp .env.docker.example .env
```

Windows PowerShell 可使用：

```powershell
Copy-Item .env.docker.example .env
```

## 使用 Docker

### 构建基础镜像

默认构建已经偏向中国大陆网络环境：

- Debian 包默认走清华镜像
- Python 包默认走清华 PyPI 镜像
- 支持通过 `HTTP_PROXY` / `HTTPS_PROXY` 透传代理

默认构建不会安装 Playwright 浏览器二进制，适合仅验证 Web/API 基础能力：

```bash
docker build -t ucrawl-web:latest .
```

如果需要显式覆盖镜像源或代理：

```bash
docker build \
  --build-arg APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian \
  --build-arg APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  --build-arg PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
  --build-arg HTTP_PROXY=http://127.0.0.1:7890 \
  --build-arg HTTPS_PROXY=http://127.0.0.1:7890 \
  -t ucrawl-web:latest .
```

### 构建带 Playwright 浏览器的镜像

如果容器需要运行依赖浏览器自动化的平台抓取逻辑，可在构建时启用：

```bash
docker build --build-arg INSTALL_PLAYWRIGHT=1 -t ucrawl-web:playwright .
```

### 启动容器

```bash
docker run --rm -p 127.0.0.1:8000:8000 \
  -e UCRAWL_USER_DATA_ROOT=/data/user_data \
  -e UCRAWL_DOWNLOAD_ROOT=/data/downloads \
  -e UCRAWL_TOOL_ROOT=/app/tools \
  -v ${PWD}/user_data:/data/user_data \
  -v ${PWD}/downloads:/data/downloads \
  -v ${PWD}/tools:/app/tools \
  ucrawl-web:latest
```

如果要启用 `N_m3u8DL-RE` 的 HLS 下载能力，请把 Linux 可执行文件放进 `./tools`，例如：

```text
tools/
└── N_m3u8DL-RE
```

容器会按以下顺序自动发现：

1. `UCRAWL_TOOL_ROOT` 指向的目录
2. 项目安装目录 / 资源目录
3. 系统 `PATH`

启动后访问：

```text
https://localhost:8000/?access_token=<Web 访问口令>
```

自动生成的口令保存在 `user_data/web-access-token`，也可以显式设置 `UCRAWL_WEB_ACCESS_TOKEN`；启动日志不会打印口令。自动生成的是本地自签名证书，浏览器首次访问会提示确认。用于局域网或公网反向代理时，应挂载受信任证书；入口会在口令校验成功后立即重定向到不含 `access_token` 的地址。

## 使用 Docker Compose

### 默认启动

```bash
docker compose up --build
```

### 带自定义端口或 Playwright 浏览器

```bash
UCRAWL_HOST_PORT=8010 UCRAWL_INSTALL_PLAYWRIGHT=1 docker compose up --build
```

### 中国大陆推荐启动方式

```bash
cp .env.docker.example .env
mkdir -p user_data downloads tools
docker compose up --build -d
```

如果你已经准备好了 Linux 版 `N_m3u8DL-RE`，放到 `./tools/N_m3u8DL-RE` 即可；无需修改代码，容器会自动优先识别 Linux 二进制。

Compose 默认映射：

- `./user_data -> /data/user_data`
- `./downloads -> /data/downloads`

## 健康检查

镜像和 Compose 都内置健康检查：

- `GET https://127.0.0.1:8000/healthz`

如果健康检查失败，优先检查：

1. 依赖是否安装成功
2. 容器内端口是否与映射配置一致
3. 卷挂载目录权限是否可写
4. 若启用了 Playwright，浏览器资源是否已按需安装

## 当前限制

- 若未提供 Linux 版 `N_m3u8DL-RE`，则 HLS 下载能力仍取决于容器内是否已安装对应命令
- Playwright 浏览器默认不内置，避免镜像无差别膨胀
- 当前镜像仍是单阶段构建，重点优先在稳定与可维护，而不是极限瘦身

若后续要支持更完整的下载链与更小的镜像，建议继续推进：

1. 为 HLS 下载链补跨平台实现，减少对 Windows-only 工具的依赖
2. 引入多阶段构建和更细的运行时资源分层
3. 视平台需求拆分 `web-basic` 与 `web-browser` 两类镜像
