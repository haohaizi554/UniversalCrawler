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

### Changed
- Unified installer version injection with `pyproject.toml`.
- Updated README, testing docs, and packaging docs to match the current project structure.
- Improved test auto-classification rules for newly added Web and plugin tests.

### Fixed
- Fixed Douyin FFmpeg progress parsing and retry refresh behavior.
- Fixed Web-side Douyin parameter initialization bottlenecks and packaging metadata drift.
