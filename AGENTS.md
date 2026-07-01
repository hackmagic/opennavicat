# OpenNavicat

**CLI-First, AI-Native** database management tool (Navicat alternative).  
Python 3.10+ | Poetry | MySQL/MariaDB (currently only MySQL connector) | Typer + Rich (CLI) | PySide6 (GUI) | aiomysql (async)

## Quick start

```bash
poetry install                           # install dependencies
poetry run opennavicat                   # CLI mode
poetry run opennavicat gui               # GUI mode
poetry run pytest tests/ -v              # all tests
poetry run pytest tests/unit/ -v         # unit tests only
```

## Developer commands

```bash
poetry run ruff check open_navicat/      # lint
poetry run mypy open_navicat/            # typecheck (non-strict)
poetry run pytest tests/ -v --cov=open_navicat  # test + coverage
poetry build                             # build sdist + wheel
```

## Architecture

- **Entry points** (`pyproject.toml` → `open_navicat.main`):
  - `cli_main()` — CLI (default; routes `gui` arg to GUI)
  - `main()` — GUI via `Application.run()`
- **CLI subcommand groups** (`open_navicat/cli/app.py`): `conn`, `query`, `schema`, `data`, `backup`, `ai`
  - Each group is a `typer.Typer()` instance registered via `app.add_typer()`
- **Service layer** (`open_navicat/services/`): singleton-per-module pattern (`ai_service`, `ConnectionManager`, etc.)
- **DAL** (`open_navicat/dal/`): `BaseConnector` ABC → `MySQLConnector` (only impl), `ConnectionPool`, `SSHTunnel`, `local_config`
- **Models** (`open_navicat/models/`): dataclass-style models (`ConnectionInfo`, `QueryResult`, `TableInfo`)
- **Config persistence**: platform-specific dir (`%APPDATA%/OpenNavicat` / `~/.config/OpenNavicat`), JSON + SQLite

## Key conventions

- All files use `from __future__ import annotations` + full type annotations
- Ruff config: line-length 100, select `E,F,I,N,W`, ignore `E501`
- Async tests: no decorator needed — `pytest.ini` sets `asyncio_mode = auto`
- i18n: custom JSON-based system (`open_navicat/i18n/`), call `t("key")` not gettext

## AI integration

Env vars override config-file settings:
- `OPENNAVICAT_AI_PROVIDER` = `openai` | `deepseek` | `ollama` | `custom`
- `OPENNAVICAT_AI_API_KEY`
- `OPENNAVICAT_AI_API_BASE`
- `OPENNAVICAT_AI_MODEL`
- `OPENNAVICAT_AI_DEBUG=true` — prints full prompt sent to LLM

## Testing quirks

- Only MySQL connector exists; tests requiring a live DB connection cannot run without a MySQL server
- `tests/integration/` and `tests/fixtures/` are empty — fixtures or integration helpers must be created if needed
- Password encryption tests need `cryptography` — safe to mock

## Build (standalone binary)

```bash
pip install pyinstaller
pyinstaller --onefile --name opennavicat open_navicat/main.py
```
