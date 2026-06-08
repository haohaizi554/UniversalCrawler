# 容器化部署说明

## 目标

当前项目的容器化支持以 `Web/API` 服务为主，不覆盖桌面 GUI 交付形态。

推荐容器模式：

- `entry.web_entry`
- `--no-qt`
- `--no-browser`

也就是：

```bash
python -m entry.web_entry --host 0.0.0.0 --port 8000 --no-qt --no-browser
```

## 为什么只支持 Web/API 容器

当前项目存在两类明显的运行时边界：

### 1. GUI 不是容器优先形态

- 桌面 GUI 基于 PyQt6
- 任务栏、系统托盘、窗口图标、原生目录选择框都偏本机桌面环境
- 这类能力适合 Windows 本地运行，不适合作为标准容器交付

### 2. 下载链存在平台差异

- `ffmpeg` 已支持系统 PATH fallback，Linux 容器可用
- `N_m3u8DL-RE` 当前仍是 `N_m3u8DL-RE.exe`，属于 Windows 发布物

因此当前容器支持矩阵应明确为：

- 支持：Web UI / REST API / WebSocket / 基于 `ffmpeg` 的下载链
- 暂不承诺：依赖 `N_m3u8DL-RE.exe` 的完整 HLS 下载能力
- 不支持：桌面 GUI / 系统托盘 / Qt 交互

## 新增资产

- [Dockerfile](../Dockerfile)
- [.dockerignore](../.dockerignore)
- [docker-compose.yml](../docker-compose.yml)

## 运行时路径约定

为了适配容器卷挂载，运行时路径支持以下环境变量覆盖：

- `UCRAWL_USER_DATA_ROOT`
- `UCRAWL_DOWNLOAD_ROOT`

默认在 Docker 资产中配置为：

- `/data/user_data`
- `/data/downloads`

这可以避免把运行时状态写进镜像层，也符合项目对 `runtime_paths.py` 统一收口的工程约束。

## 使用 Docker

### 构建镜像

```bash
docker build -t ucrawl-web:latest .
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

```bash
docker compose up --build
```

默认映射：

- `./user_data -> /data/user_data`
- `./downloads -> /data/downloads`

## 健康检查

镜像已内置健康检查：

- `GET /api/ping`

如果健康检查失败，通常先看：

1. 依赖是否安装成功
2. 端口是否被占用
3. 卷挂载目录权限是否可写

## 当前限制

- Linux 容器中不承诺 `N_m3u8DL-RE.exe` 相关能力
- 若后续要支持完整 HLS 下载链，建议：
  - 引入 Linux 可执行的 `N_m3u8DL-RE`
  - 或为 HLS 下载链补一个纯 Python / ffmpeg 优先降级方案
- 当前镜像仍安装完整 `requirements.txt`，体积不是最小化形态
- 若后续确定“容器只跑 Web/API”，可进一步拆出专用 `requirements-web.txt`

## 建议下一步

如果要把容器化推进到生产可用，建议继续做三件事：

1. 补 `release` / `container` CI，自动构建镜像
2. 拆分 `requirements-web.txt`，降低镜像体积
3. 把 HLS 下载链从 Windows-only 工具抽象成跨平台策略
