# Changelog

All notable changes to OpenNavicat are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/) and this project adheres to [Semantic Versioning](https://semver.org/).

---

## [0.9.3] - 2026-10-30

### Fixed

- **PyPI publishing could never succeed.** The `PYPI_API_TOKEN` secret was
  stored in a GitHub *environment* named `PYPI_API_TOKEN`, but the publish
  job never declared that environment - and a job only receives an
  environment's secrets when it declares it. `secrets.PYPI_API_TOKEN`
  therefore resolved to an empty string and the upload failed
  authentication. The job now declares `environment: PYPI_API_TOKEN`.
- **The Docker image could not build.** The Dockerfile ran
  `pip install open-navicat`, which can only install a version PyPI actually
  has; while publishing was broken that pulled an old release or failed
  outright. It now builds the wheel from the checked-out tree, so the image
  always matches the commit that triggered it. `.dockerignore` no longer
  excludes `pyproject.toml`, `poetry.lock`, `README.md` and `LICENSE`, which
  are build inputs the wheel cannot be produced without.

## [0.9.2] - 2026-10-30

### Fixed

- **Packaged builds emitted incomplete DDL.** The frozen binary cannot see a
  `pg_dump` that lives outside its PATH, so the catalog-reconstruction
  fallback was in practice the only implementation - and it emitted bare
  columns only, dropping the table's sequence, indexes, foreign keys and
  CHECK constraints. It now builds the full statement set in dependency
  order (sequence, table, OWNED BY, indexes, foreign keys), verified by
  executing the output on a live server and comparing the resulting
  structure against the original.
- Release notes published `pip install open-navicat==v0.9.1`; a version in
  a requirement must not carry the `v` prefix.

## [0.9.1] — 2026-10-30

PostgreSQL was the least-tested engine and it showed: a table list could render
empty while the database was full, and a structure copy could report success
without creating a single table. All of this was found by running every feature
against a live PostgreSQL 18.6 rather than by reading code.

### Fixed

**PostgreSQL metadata (the reported empty table list)**

- `list_tables` / `list_views` / `list_routines` / `list_triggers` ignored the
  `database` argument and always read the pool's own database, so every node in
  the object tree showed the same list. They now open a session per target
  database and read the correct catalogs.
- Only schema `public` was visible. All non-system schemas are listed now, and
  objects outside `public` are shown as `schema.name`.
- `list_tables_with_info` was not overridden, so the Table List grid rendered
  blank metadata. It now reports real on-disk size (`pg_total_relation_size`)
  and access method (`pg_am`).
- `get_table_info` hard-coded schema `public`. It accepts `schema.table` and
  resolves a bare name server-side through `search_path` via `to_regclass`.

**Cross-database references**

- `quote_qualified` emitted `"database"."table"` for PostgreSQL, which the
  server rejects outright (*cross-database references are not implemented*).
  PostgreSQL now qualifies by schema only; every other engine is byte-identical.
- A **bare** name is deliberately left unqualified: forcing `"public"` was
  measured to break tables reached through a custom or `"$user"` search_path.

**Queries and DDL**

- `execute_many` raised `AttributeError: 'NoneType' object has no attribute
  'split'` on every call: asyncpg's `executemany` returns `None`, not a command
  tag. Bulk writes were reported as failed after succeeding.
- Multi-statement DDL could not be executed at all — `prepare()` rejects it with
  *cannot insert multiple commands into a prepared statement*. Add a
  quote/comment/dollar-quote-aware splitter and route scripts to the simple-query
  protocol. This is what made structure copy and pg_dump output usable.
- `EXPLAIN FORMAT=JSON` is MySQL-only syntax; PostgreSQL answered *syntax error
  at or near "FORMAT"*. Plans are now requested in each engine's own spelling.
- `get_create_table_sql` called `pg_get_tabledef`, a pgAdmin helper that does
  **not exist** in PostgreSQL, so "copy DDL" always yielded a placeholder
  comment. It now uses `pg_dump` (with the table's owned sequences, which a
  `-t name` pattern alone omits) and rebuilds from the catalog as a fallback.

**Data and metadata correctness**

- Foreign-key actions were always reported as `NO ACTION`: PostgreSQL's
  `"char"` columns come back from asyncpg as **bytes** (`b'c'`), which matched
  no lookup key. `ON DELETE CASCADE` now reads correctly.
- Row counts showed 0 for any table that had never been `ANALYZE`d
  (`reltuples = -1`). Unanalyzed tables now fall back to a real `COUNT(*)`.
- Cross-schema copies failed with *schema "sales" does not exist*; the target
  schema is created first. A failed structure copy is now reported instead of
  silently counting as success.

**Other**

- `conn add` with an existing name created a new row every run, because
  profiles were keyed by a randomly generated id. Saving is now keyed by name;
  one local database had accumulated 189 duplicate entries.

### Changed

- Optional drivers and `paramiko`/`cryptography` are imported lazily, so a CLI
  invocation no longer loads every connector it does not use
  (`import open_navicat.dal`: 0.114 s, zero heavy drivers loaded).

## [0.9.0] — 2026-10-18

> Note: the MongoDB/Redis work below was previously listed under `[0.8.0]`, but
> it landed in `4c5c6fb`/`3a94cf8`, *after* the `v0.8.0` tag (`c1092ce`). The
> `v0.8.0` release shipped only the Phase 6 items, which are now listed under
> their own heading.

### Added
- MongoDB connector (async motor driver, schema inference from documents)
- Redis connector (async redis.asyncio driver, key browsing + basic commands)
- Both as optional extras: `pip install open-navicat[mongodb,redis]`
- Connection dialog + CLI: engine selection for MongoDB/Redis
- SQL Server, ClickHouse and Oracle connectors, each an optional extra
- Driver-layer refactor: `BaseConnector` contract, `DRIVER_REGISTRY`, DSN
  parse/format — adding an engine is one registry row plus one connector module
- Unified `NavicatError` (`code`/`stage`/`recoverable`/`retryable`, redacted at
  construction so credentials cannot reach logs)
- Streaming import (CSV, TSV, JSON, JSONL, XLSX, Parquet) and export (CSV,
  TSV, JSON, Markdown, XLSX, SQL) with format detection, delimiter sniffing
  and batched iteration
- Cross-engine SQL layer: identifier quoting, `OFFSET/FETCH` limit clauses,
  dependency-ordered schema-diff scripts, statement classification
- Migration pipeline with dry-run planning and per-column type coercion
- Plugin platform MVP: signed `.onvpkg` packages (Ed25519), 14-permission
  catalog with deny-by-default hooks, install/enable/disable lifecycle
- MCP server package (`open_navicat/mcp/`) behind the optional `[mcp]` extra
- Query budget: explicit timeout/cancel racing, write-aware cache invalidation

### Changed
- `conn add` command: new `--engine/-e` option
  (mysql|postgresql|sqlite|mongodb|redis|sqlserver|clickhouse|oracle)
- `ConnectionPool` routes by registry lookup instead of `if/elif` branches
- Optional drivers bumped for Python 3.13/3.14 wheels: `asyncpg` 0.31,
  `clickhouse-connect` 0.10, `oracledb` 3.3, `pytest-asyncio` 1.4
- CLI grew from 59 to 79 commands across 12 command groups, plus the `init`
  wizard and an `ask` alias for `ai`
- i18n grew from 1282 to 1383 keys (zh_CN / en_US, key-symmetric)

### Fixed
- Unknown/legacy theme names no longer crash the GUI at startup (issue #1)
- Connection failures now surface the real cause and an install hint instead of
  a bare "Could not connect to the server." (issue #2)
- Release binaries were built with a bare `poetry install`, so published
  executables contained **no optional driver at all** — PostgreSQL could not
  connect. Build and test now use `--all-extras`, and both PyInstaller specs
  declare the drivers as hidden imports
- `DuckDBConnector` skipped `super().__init__()` and crashed on its own failure
  path; `is_installed()` probed the wrong name
- Saved connections lost their engine on reload (no `engine` column)
- Flaky `test_generate_nullable_can_be_none` (mocked `random.random`)

### Build
- CI and release matrices install all extras; Python 3.13 and 3.14 are green
- macOS builds no longer fail: PyInstaller's contributed `hook-pyodbc.py`
  imports the extension at analysis time, and the macOS pyodbc wheel links
  against Homebrew's unixODBC, which the runner does not have. A local
  `hooks/hook-pyodbc.py` (empty `hiddenimports`) now takes priority over it
- Corrected the documented binary sizes, which had been off by ~3×: measured
  v0.9.0 assets are CLI 50.6 MB / GUI 90.6 MB on Windows x64 (not ~15 MB /
  ~120 MB), 51.3 MB / 79.8 MB on macOS arm64, and 86.0 MB / 146.9 MB on Linux
  x64 — the DuckDB manylinux wheel alone is 20 MB versus 12 MB on Windows
- Excluded dev-only packages (`mypy`, `setuptools`, `pytest`, …) from the CLI
  build, saving ~1.4 MB

## [0.8.0] — 2026-07-10

### Added
- FilterPanel with 16 operators, multi-condition AND and NOT negation
- Transaction control toolbar (Begin/Commit/Rollback)
- Cell editor dialog for long text and JSON
- Column type icons in the data grid
- Empty-table action plus a maintenance submenu
  (CHECK/OPTIMIZE/REPAIR/ANALYZE)
- Create a BI workspace from the table context menu
- SQL editor: line numbers, code folding (BEGIN/END), bracket highlighting
- Import formats: dBase (`*.dbf`), MS Access (`*.mdb`/`*.accdb`), Paradox
  (`*.db`)
- `DataGeneratorService` with 30+ pattern matchers and a
  `--method auto|ai|pattern` CLI option
- `AutoRecoveryService` (30 s auto-save), favorites, multi-window management
  (Ctrl+Tab), table view profiles, tab behavior configuration, telemetry toggle

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
