# OpenNavicat

**CLI-First, AI-Native** database management tool (Navicat alternative).  
Python 3.10+ | Poetry | MySQL + PostgreSQL + SQLite + DuckDB + SQL Server + ClickHouse + Oracle + MongoDB + Redis | Typer + Rich (CLI) | PySide6 (GUI)

## Quick start

```bash
poetry install                                    # install dependencies
poetry install --extras postgresql                # with PostgreSQL support
poetry install --extras "mongodb redis"           # with MongoDB + Redis support
poetry install --extras "sqlserver clickhouse oracle"   # with SQL Server / ClickHouse / Oracle drivers
poetry run opennavicat                            # CLI mode (79 commands)
poetry run opennavicat gui                        # GUI mode
poetry run pytest tests/unit/ -v                  # unit tests (1456)
poetry run pytest tests/integration/ -v           # integration tests (16, needs Docker)
```

## Developer commands

```bash
poetry run ruff check open_navicat/               # lint (ruff)
poetry run mypy open_navicat/                     # typecheck (non-strict)
poetry run python scripts/build_dependency_matrix.py --check  # architecture guard (CI)
poetry run pytest tests/ -v --cov=open_navicat    # test + coverage
poetry build                                      # build sdist + wheel
```

## Architecture

- **Entry points** (`pyproject.toml` → `open_navicat.main`):
  - `cli_main()` — CLI (default; routes `gui` arg to GUI)
  - `main()` — GUI via `Application.run()`
- **CLI subcommand groups** (`open_navicat/cli/app.py`): `conn`, `query`, `plugin`, `schema`, `data`, `backup`, `ai`, `snippet`, `cloud`, `sql`, `template`, `mcp` (+ `init` leaf command, + `ask` alias for `ai`)
  - Each group is a `typer.Typer()` instance registered via `app.add_typer()`
  - 79 commands total (conn 12, plugin 12, ai 15, backup 9, schema 8, query 6, data 6, snippet 4, sql 2, template 2, cloud 1, mcp 1, init 1)
  - `ask` re-registers `ai_app`, so its 15 subcommands are aliases — count them once, not twice
- **Service layer** (`open_navicat/services/`): singleton-per-module pattern
  - `ai_service` — LLM integration with ReAct agent, Schema RAG, chat persistence
  - `backup_service` — backup/restore with mysqldump/pg_dump
  - `sync_engine` / `data_sync_engine` — schema + data comparison (MySQL/PostgreSQL)
  - `scheduler` / `automation_service` — APScheduler-based job scheduling
  - `ConnectionManager` — pool management + SSH tunnels
- **Drivers** (`open_navicat/drivers/`) — see `drivers/README.md`:
  - `BaseConnector` ABC → the connector contract every engine implements
  - `registry.py` — `DRIVER_REGISTRY` (`DriverSpec`) + `get_connector_class()` / `available_engines()`; **adding an engine = one registry row + one connector module** (no pool/CLI/GUI edits)
  - 9 connectors: mysql, postgresql, sqlite, duckdb, sqlserver, clickhouse, oracle, mongodb, redis
  - `dsn.py` — `parse_dsn` / `dsn_to_connection` / `info_to_dsn`
  - Sync drivers (sqlserver/clickhouse/oracle) bridge to async via a **single-thread executor** per connector
- **DAL** (`open_navicat/dal/`):
  - `base_connector.py` + `*_connector.py` are compatibility shims re-exporting `drivers/`
  - `ConnectionPool` — engine selection is registry lookup (no `if/elif` branches); records structured `last_error`
  - `SSHTunnel` — async SSH tunnel
  - `local_config` — JSON + SQLite persistence
- **Errors** (`open_navicat/errors.py`): `NavicatError` with `code / message_key / detail / source / stage / recoverable / retryable`; codes `ONV-<域>-<序号>`, auto-redacted (`redact()`)
- **Models** (`open_navicat/models/`): dataclass-style models (`ConnectionInfo`, `QueryResult`, `TableInfo`, `BackupInfo`, `SyncResult`, etc.)
- **Config persistence**: platform-specific dir (`%APPDATA%/OpenNavicat` / `~/.config/OpenNavicat`), JSON + SQLite
- **Layering** (enforced in CI by `scripts/build_dependency_matrix.py --check`):
  L0 `models`/`errors` → L1 `drivers`/`dal`/`utils`/`config`/`i18n` → L2 `services`/`plugin` → L3 `cli`/`ui`
  Lower layers must never import upward.

## Key conventions

- All files use `from __future__ import annotations` + full type annotations
- Ruff config: line-length 100, select `E,F,I,N,W`, ignore `E501`
- Async tests: no decorator needed — `pytest.ini` sets `asyncio_mode = auto`
- Connector subclasses **must** call `super().__init__()` (sets `_last_error`; omitting it makes the failure path crash and mask the real error)
- Driver modules must raise `DriverNotFoundError` (`ONV-DRV-002`) when their third-party package is missing — never silently `return False`
- i18n: custom JSON-based system (`open_navicat/i18n/`), call `t("key")` not gettext
  - zh_CN / en_US must stay key-symmetric; `t()` echoes the key when untranslated
  - All UI-visible strings use `t()`, zero hardcoded Chinese/English
- Optional deps: `asyncpg` `[postgresql]`, `motor` `[mongodb]`, `redis` `[redis]`, `pyodbc` `[sqlserver]`, `clickhouse-connect` `[clickhouse]`, `oracledb` `[oracle]` — none are default installs

## AI integration

Env vars override config-file settings:
- `OPENNAVICAT_AI_PROVIDER` = `openai` | `deepseek` | `ollama` | `custom`
- `OPENNAVICAT_AI_API_KEY`
- `OPENNAVICAT_AI_API_BASE`
- `OPENNAVICAT_AI_MODEL`
- `OPENNAVICAT_AI_DEBUG=true` — prints full prompt sent to LLM

AI features include:
- `ai agent` — ReAct multi-step reasoning with Schema RAG
- `ai chat` — interactive chat with history persistence (SQLite)
- `ai config` — CLI-configurable provider settings

## Testing

- **1456 unit tests**: services, DAL, models, CLI, i18n, GUI, utils (all mock-based)
- **16 integration tests**: MySQL 8.0 + PostgreSQL 16 via testcontainers (requires Docker)
- Run integration tests: `pytest tests/integration/ -v` (auto-skips if Docker unavailable)
- Password encryption tests need `cryptography` — safe to mock

## Build (standalone binary)

Two PyInstaller spec files for dual packaging:

```bash
pip install pyinstaller

# CLI package (~50 MB on Windows, no Qt)
pyinstaller opennavicat-cli.spec

# GUI package (~86 MB on Windows, with PySide6)
pyinstaller opennavicat-gui.spec
```

Sizes are onefile executables measured on Windows x64 with Python 3.12. The
Linux CLI build is larger (~68 MB) because the DuckDB manylinux wheel is bigger
than its Windows counterpart; DuckDB alone is ~12 MB compressed and is the
single largest component after the pure-Python archive.

Version info is generated from `open_navicat/__init__.py` at build time — update only that file.

Multi-platform builds via GitHub Actions (release.yml): Win x64, macOS ARM64, Linux x64 — CLI + GUI per platform.
