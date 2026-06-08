# Universal Crawler Pro

[中文](README.md) | English

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" />
  <img alt="PyQt6" src="https://img.shields.io/badge/Framework-PyQt6-41CD52?logo=qt&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/Web_UI-FastAPI-009688?logo=fastapi&logoColor=white" />
  <img alt="Windows" src="https://img.shields.io/badge/Platform-Windows_10%20%7C%2011-0078D4?logo=windows&logoColor=white" />
  <img alt="Playwright" src="https://img.shields.io/badge/Browser-Playwright_Chromium-2EAD33?logo=playwright&logoColor=white" />
  <img alt="License" src="https://img.shields.io/badge/License-Personal%20Non--Commercial-red" />
</p>

**Universal Crawler Pro** is a Windows-oriented multi-platform media crawling and downloading workstation built with **Python + PyQt6 + Playwright + FastAPI**. It combines desktop GUI workflows, Web UI control, unified download scheduling, local asset management, and production-minded engineering practices in a single codebase.

## Highlights

- **Desktop-first experience**: native PyQt6 GUI for daily use on Windows 10/11.
- **Web/API mode**: `entry.web_entry` exposes Web UI, REST API, and WebSocket control.
- **Unified download pipeline**: queue scheduling, downloader routing, and external tool integration are managed by shared core services.
- **Plugin-oriented platform integration**: platform capabilities are injected through `app/core/plugins/`.
- **Debuggability**: traceable logs, error summaries, and safer diagnostic output.
- **Testability**: the repository already includes targeted tests for CLI, Web, packaging, core services, and browser-facing flows.

## Quick Start

### Local source setup

```bash
pip install -e .
playwright install chromium
```

Required external tools for the full Windows desktop workflow:

- `ffmpeg.exe`
- `N_m3u8DL-RE.exe`

### Desktop GUI

```bash
python main.py
```

### Web UI

```bash
python -m entry.web_entry --host 127.0.0.1 --port 8000
```

## Docker

Container support is intentionally scoped to the **Web/API** runtime only.

- Uses `entry.web_entry --no-qt --no-browser`
- Does not provide the desktop GUI or Qt tray experience
- Supports the `ffmpeg` path in Linux containers
- Does not promise the Windows-only `N_m3u8DL-RE.exe` HLS path

### Build and run

```bash
docker build -t ucrawl-web:latest .
docker compose up --build
```

If you need a local environment file:

```bash
cp .env.docker.example .env
```

To build an image that also installs Playwright browser binaries:

```bash
docker build --build-arg INSTALL_PLAYWRIGHT=1 -t ucrawl-web:playwright .
```

More details:

- [Containerization Guide](docs/containerization.md)

## Documentation

- [Architecture](docs/architecture.md)
- [API Notes](docs/api.md)
- [Configuration](docs/config.md)
- [Testing Guide](docs/testing.md)
- [Packaging Guide](docs/packaging.md)
- [Containerization Guide](docs/containerization.md)

## License

This repository is **not MIT anymore** and is **not an open commercial-use license**.

- Copyright remains with the individual author.
- Personal learning, research, and non-commercial development are allowed.
- Commercial use is prohibited without prior written permission from the author.

See the full text in [LICENSE](LICENSE).
