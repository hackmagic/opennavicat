# Changelog

All notable changes to OpenNavicat are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/) and this project adheres to [Semantic Versioning](https://semver.org/).

---

## [0.8.0] — 2026-07-10

### Added
- MongoDB connector (async motor driver, schema inference from documents)
- Redis connector (async redis.asyncio driver, key browsing + basic commands)
- Both as optional extras: `pip install open-navicat[mongodb,redis]`
- Connection dialog + CLI: engine selection for MongoDB/Redis
- 41 unit tests for new connectors

### Changed
- `conn add` command: new `--engine/-e` option (mysql|postgresql|sqlite|mongodb|redis)
- ConnectionPool routes to appropriate connector by engine type

### Fixed
- Flaky `test_generate_nullable_can_be_none` (mocked random.random)

## [0.7.0] — 2026-07-06

### Added
- Connection grouping/folders with display colors
- Table right-click menu: profile, share URI, desktop shortcut, permissions
- SQL autocomplete (information_schema-based)
- BI Dashboard with self-drawn charts (no external libs)
- ER Model Designer (conceptual/logical/physical levels)
- Object Designer (table/view/procedure/event/trigger)
- AICopilot sidebar with `!sql` execution and schema viewing
- QueryBuilder widget (visual drag-and-drop)
- Data dictionary with HTML/PDF export
- Condition formatting & foreign key picker in TableViewer
- Cloud database discovery (scan local connections)
- Backup history persistence (SQLite)
- i18n: zh_CN + en_US (1282 keys, zero hardcoded strings)
- 30 UI module import tests + 6 service module tests
- Multi-platform PyInstaller builds (Win/Mac/Linux, CLI + GUI)

### Changed
- Unified entry point: `opennavicat` (CLI) / `opennavicat gui` (GUI)
- Version metadata centralized in `__init__.py`
- AsyncPG made optional (`[postgresql]` extra)
- PySide6 packaging: precise Qt module selection (~120 MB → smaller)

### Fixed
- conftest.py: conditional PySide6 mock for pytest-qt compatibility
- Dropped Python 3.10 from CI (EOL, PySide6 6.11+ no longer ships for it)
- All stub implementations completed (4 items)
- Window geometry restore, theme selector, dialog i18n
- Packaging: hidden-imports for theme modules, Qt DLL collection

## [0.3.1] — 2026-07-02

### Fixed
- aiomysql 0.3.0, cryptography 48.0.0, paramiko 5.0.0 CVE fixes
- PyInstaller --windowed for headless EXE
- Schema migration for conn_group column

## [0.3.0] — 2026-07-01

### Added
- AI features: NL2SQL, query optimization, explain, fix, data generation
- AI ReAct agent with Schema RAG and chat history (SQLite)
- AI: data quality analysis, anomaly detection, SQL review
- Model Designer with conceptual/logical/physical levels
- Schema sync & data sync (MySQL ↔ PostgreSQL)
- AutomationService (APScheduler: backup/query/sync)
- Snippet service with variable substitution
- SQL formatter/generator utilities
- Full i18n framework (JSON-based)
- 16 integration tests (MySQL 8.0 + PostgreSQL 16 via testcontainers)

### Changed
- AsyncPG moved to optional `[postgresql]` extra
- Refactored backup commands to use BackupService
- Removed open_navicat_rs (Tauri version) — forked separately

## [0.2.0] — 2026-06-30

### Added
- SQLite connector (aiosqlite)
- MySQL/PostgreSQL integration tests
- Documentation: architecture, data flow, AI module, development guide

## [0.1.0] — 2026-06-29

### Added
- Initial release
- MySQL/MariaDB + PostgreSQL connectors
- CLI: connection management, query, schema, data, backup
- Basic GUI (PySide6) with object browser, SQL editor, table viewer
- SSH tunnel support (asyncssh)
- Connection pooling, metadata caching
- Output formatting (table/json/csv/markdown)
- CI/CD: GitHub Actions, multi-platform builds
- 80 unit tests
