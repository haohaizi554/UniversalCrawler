# 容器化部署说明

## 目标

当前项目的容器化支持聚焦在 `Web/API` 运行形态，不覆盖桌面 GUI 交付。

推荐容器入口：

- `entry.web_entry`
- `--no-qt`
- `--no-browser`

容器内最终等价于：

```bash
python -m entry.web_entry --host 0.0.0.0 --port 8000 --no-qt --no-browser
```

## 为什么只支持 Web/API 容器

当前项目存在两个明确的运行时边界：

### 1. GUI 不适合作为标准容器交付

- 桌面 GUI 基于 `PyQt6`
- 任务栏、系统托盘、窗口图标、原生目录选择框都偏本机桌面环境
- 这类能力适合 Windows 本地运行，不适合作为标准容器形态交付

### 2. 下载链存在跨平台差异

- `ffmpeg` 已支持系统 `PATH` fallback，Linux 容器可用
- `N_m3u8DL-RE` 当前仍以 `N_m3u8DL-RE.exe` 形式存在，属于 Windows 发布物

因此当前容器支持矩阵应明确为：

- 支持：Web UI / REST API / WebSocket / 基于 `ffmpeg` 的下载链
- 条件支持：依赖 Playwright 的平台抓取能力，需要在构建时显式安装浏览器
- 暂不承诺：依赖 `N_m3u8DL-RE.exe` 的完整 HLS 下载能力
- 不支持：桌面 GUI / 系统托盘 / Qt 交互

## 当前容器资产

- [Dockerfile](../Dockerfile)
- [.dockerignore](../.dockerignore)
- [docker-compose.yml](../docker-compose.yml)
- [requirements-web.txt](../requirements-web.txt)
- [docker/entrypoint.sh](../docker/entrypoint.sh)
- [.env.docker.example](../.env.docker.example)

## 工程化约束

当前容器实现新增了以下约束：

- 镜像使用 `requirements-web.txt`，明确排除 `PyQt6` 和测试类依赖
- 镜像以非 root 用户 `ucrawl` 运行
- 启动通过 `tini + docker/entrypoint.sh` 收口，统一解析容器环境变量
- 数据目录通过卷挂载写入 `/data/user_data` 和 `/data/downloads`
- Compose 与镜像都内置 `/api/ping` 健康检查

## 运行时环境变量

容器支持以下关键环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `UCRAWL_HOST` | `0.0.0.0` | Web 服务监听地址 |
| `UCRAWL_PORT` | `8000` | 容器内部监听端口 |
| `UCRAWL_NO_QT` | `1` | 容器内默认关闭 Qt |
| `UCRAWL_NO_BROWSER` | `1` | 容器内默认不自动拉起浏览器 |
| `UCRAWL_USER_DATA_ROOT` | `/data/user_data` | 用户数据目录 |
| `UCRAWL_DOWNLOAD_ROOT` | `/data/downloads` | 下载目录 |
| `UCRAWL_EXTRA_ARGS` | 空 | 透传额外启动参数 |

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

默认构建不会安装 Playwright 浏览器二进制，适合仅验证 Web/API 基础能力：

```bash
docker build -t ucrawl-web:latest .
```

### 构建带 Playwright 浏览器的镜像

如果容器需要运行依赖浏览器自动化的平台抓取逻辑，可在构建时启用：

```bash
docker build --build-arg INSTALL_PLAYWRIGHT=1 -t ucrawl-web:playwright .
```

### 启动容器

```bash
docker run --rm -p 8000:8000 \
  -e UCRAWL_USER_DATA_ROOT=/data/user_data \
  -e UCRAWL_DOWNLOAD_ROOT=/data/downloads \
  -v ${PWD}/user_data:/data/user_data \
  -v ${PWD}/downloads:/data/downloads \
  ucrawl-web:latest
```

启动后访问：

```text
http://localhost:8000
```

## 使用 Docker Compose

### 默认启动

```bash
docker compose up --build
```

### 带自定义端口或 Playwright 浏览器

```bash
UCRAWL_HOST_PORT=8010 UCRAWL_INSTALL_PLAYWRIGHT=1 docker compose up --build
```

Compose 默认映射：

- `./user_data -> /data/user_data`
- `./downloads -> /data/downloads`

## 健康检查

镜像和 Compose 都内置健康检查：

- `GET /api/ping`

如果健康检查失败，优先检查：

1. 依赖是否安装成功
2. 容器内端口是否与映射配置一致
3. 卷挂载目录权限是否可写
4. 若启用了 Playwright，浏览器资源是否已按需安装

## 当前限制

- Linux 容器中不承诺 `N_m3u8DL-RE.exe` 相关能力
- Playwright 浏览器默认不内置，避免镜像无差别膨胀
- 当前镜像仍是单阶段构建，重点优先在稳定与可维护，而不是极限瘦身

若后续要支持更完整的下载链与更小的镜像，建议继续推进：

1. 为 HLS 下载链补跨平台实现，减少对 Windows-only 工具的依赖
2. 引入多阶段构建和更细的运行时资源分层
3. 视平台需求拆分 `web-basic` 与 `web-browser` 两类镜像
