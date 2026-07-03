# OpenNavicat

**CLI-First, AI-Native** database management tool (Navicat alternative).  
Python 3.10+ | Poetry | MySQL + PostgreSQL | Typer + Rich (CLI) | PySide6 (GUI) | aiomysql + asyncpg (async)

## Quick start

```bash
poetry install                                    # install dependencies
poetry install --extras postgresql                # with PostgreSQL support
poetry run opennavicat                            # CLI mode (40+ commands)
poetry run opennavicat gui                        # GUI mode
poetry run pytest tests/unit/ -v                  # unit tests (80)
poetry run pytest tests/integration/ -v           # integration tests (16, needs Docker)
```

## Developer commands

```bash
poetry run ruff check open_navicat/               # lint (ruff)
poetry run mypy open_navicat/                     # typecheck (non-strict)
poetry run pytest tests/ -v --cov=open_navicat    # test + coverage
poetry build                                      # build sdist + wheel
```

## Architecture

- **Entry points** (`pyproject.toml` → `open_navicat.main`):
  - `cli_main()` — CLI (default; routes `gui` arg to GUI)
  - `main()` — GUI via `Application.run()`
- **CLI subcommand groups** (`open_navicat/cli/app.py`): `conn`, `query`, `schema`, `data`, `backup`, `ai`
  - Each group is a `typer.Typer()` instance registered via `app.add_typer()`
  - 40+ commands total (7 conn, 6 schema, 4 data, 9 backup, 10 ai, 5 query)
- **Service layer** (`open_navicat/services/`): singleton-per-module pattern
  - `ai_service` — LLM integration with ReAct agent, Schema RAG, chat persistence
  - `backup_service` — backup/restore with mysqldump/pg_dump
  - `sync_engine` / `data_sync_engine` — schema + data comparison (MySQL/PostgreSQL)
  - `scheduler` / `automation_service` — APScheduler-based job scheduling
  - `ConnectionManager` — pool management + SSH tunnels
- **DAL** (`open_navicat/dal/`):
  - `BaseConnector` ABC → `MySQLConnector` + `PostgreSQLConnector`
  - `ConnectionPool` — per-connector async pool management
  - `SSHTunnel` — async SSH tunnel with asyncssh
  - `local_config` — JSON + SQLite persistence
- **Models** (`open_navicat/models/`): dataclass-style models (`ConnectionInfo`, `QueryResult`, `TableInfo`, `BackupInfo`, `SyncResult`, etc.)
- **Config persistence**: platform-specific dir (`%APPDATA%/OpenNavicat` / `~/.config/OpenNavicat`), JSON + SQLite

## Key conventions

- All files use `from __future__ import annotations` + full type annotations
- Ruff config: line-length 100, select `E,F,I,N,W`, ignore `E501`
- Async tests: no decorator needed — `pytest.ini` sets `asyncio_mode = auto`
- i18n: custom JSON-based system (`open_navicat/i18n/`), call `t("key")` not gettext
  - 1265 keys per language (zh_CN / en_US), verified symmetric after each change
  - All UI-visible strings use `t()`, zero hardcoded Chinese/English
- Optional deps: asyncpg is `[postgresql]` extra, not default install

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

- **80 unit tests**: services, DAL, models, CLI, i18n, GUI, utils (all mock-based)
- **16 integration tests**: MySQL 8.0 + PostgreSQL 16 via testcontainers (requires Docker)
- Run integration tests: `pytest tests/integration/ -v` (auto-skips if Docker unavailable)
- Password encryption tests need `cryptography` — safe to mock

## Build (standalone binary)

Two PyInstaller spec files for dual packaging:

```bash
pip install pyinstaller

# CLI package (~15 MB, no Qt)
pyinstaller opennavicat-cli.spec

# GUI package (~120 MB, with PySide6)
pyinstaller opennavicat-gui.spec
```

Version info is generated from `open_navicat/__init__.py` at build time — update only that file.

Multi-platform builds via GitHub Actions (release.yml): Win x64, macOS ARM64, Linux x64 — CLI + GUI per platform.
