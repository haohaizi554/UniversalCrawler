# Changelog

All notable changes to this project are documented in this file.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and version numbers are aligned with the project version declared in `pyproject.toml`.

## [Unreleased]

### Added
- Added shared packaging metadata via `packaging/project_meta.py`.
- Added maintainers' release guide in `docs/packaging.md`.
- Added naming rules for tests in `tests/NAMING.md`.
- Added high-value tests for Web workflows, script injection, plugin discovery, and WebSocket dispatch.
- Added repository-level `LICENSE`, `MANIFEST.in`, and `.gitattributes`.
- Added `README_EN.md` as the English companion to the default Chinese README.
- Added Docker runtime helper assets such as `requirements-web.txt`, `docker/entrypoint.sh`, and `.env.docker.example`.
- Added Docker build validation workflow in `.github/workflows/docker-build.yml`.

### Changed
- Unified installer version injection with `pyproject.toml`.
- Updated README, testing docs, and packaging docs to match the current project structure.
- Improved test auto-classification rules for newly added Web and plugin tests.
- Replaced the previous MIT wording with a personal non-commercial license.
- Expanded the root README with direct Docker usage guidance and language switch links.
- Expanded packaging documentation to include `project_meta.py`, `runtime_paths.py`, and the sync contract across build scripts, docs, and tests.
- Hardened desktop media deletion so the GUI releases the active media source before removing files.

### Fixed
- Fixed Douyin FFmpeg progress parsing and retry refresh behavior.
- Fixed Web-side Douyin parameter initialization bottlenecks and packaging metadata drift.
- Fixed Bilibili spider thread regressions and ensured single-item stream failures no longer terminate the whole task loop.
- Removed leftover temporary debug probes from Kuaishou, Douyin, FFmpeg, and Web frontend code paths.
- Filled missing XiaoHongShu regression coverage for route dispatch, HTML fallback, 461 cooldown, and downloader header propagation.
