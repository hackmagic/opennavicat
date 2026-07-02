# Changelog

All notable changes to OpenNavicat will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.5.0] - 2026-07-01

### Added

#### Snippet Management
- SnippetManagerDialog: CRUD + preview + variable substitution (`{{var}}`)
- Dynamic snippet menu in SQL editor (DB-backed + built-in templates)
- Right-click "Save as snippet" from editor
- CLI: `snippet list|add|remove|show`

#### Multi-Round Schema Design
- `AIService.design_schema_iterative()` method for incremental schema changes
- CLI `ai schema` — interactive session with `/deploy` `/show` `/done`

#### Conversational Query Builder
- CLI `ai build` — focused query-building mode with `/run` to execute
- Iterative refinement: "add filter", "join with orders" etc.

#### CI/CD Dependency Scanning
- `pip-audit` step in CI workflow
- Dedicated `security-audit.yml` (weekly schedule + manual trigger, pip-audit + safety)
- `ConnectionInfo.group` field + `conn_group` DB column
- ObjectBrowser search bar with real-time filtering
- Connection folder groups in tree view with drag-drop support
- Connection display colors
- CLI: `conn group list|rename|delete`
- CLI: `conn export <name>`, `conn import <file>`
- i18n: `browser.search_connections`

#### AI Function Calling
- Native LLM tool calls (`search_schema`, `list_tables`, `execute_sql`)
- All 4 backends support tools parameter (OpenAI/DeepSeek/Ollama/Custom)
- Backward-compatible `_call_llm_text()` wrapper
- Agent rewritten to use native `tool_calls` instead of fragile text JSON parsing

#### Data Viewer Enhancements
- Form view mode (single record, vertical layout, Prev/Next navigation)
- BLOB viewer dialog (image/text/hex dump)
- BLOB auto-detection and truncated display in table grid
- BLOB double-click to open viewer

#### Query Result Cache
- LRU cache with TTL (default 60s, max 256 entries)
- Auto-caches SELECT/WITH queries
- Pluggable: injects into QueryEngine

## [0.4.0] - 2026-07-01

### Added

#### SQL Autocomplete Enhancement
- Intelligent column name autocomplete from `information_schema`
- Support `table.column`, `` `table`.`column` ``, and bare column names
- Column names refresh when switching databases

#### Automation Service Extension
- Scheduled query execution (`add_query_job`)
- Scheduled schema/data sync (`add_sync_job`)
- Scheduler panel: run now for query/sync/backup jobs

#### Backup History Persistence
- Backup records stored in SQLite (survives restarts)
- Last 100 backup records retained

## [0.3.0] - 2026-07-01

### Added

#### SQLite Support
- Full SQLite connector via aiosqlite (WAL mode, foreign keys)
- Complete metadata: tables, views, columns, indexes, foreign keys
- Full CRUD: execute, fetch_page, batch_insert, update_row, delete_row
- Connection dialog: SQLite option with file path input
- `aiosqlite` added as default dependency

## [0.2.0] - 2026-07-01

### Added

#### PostgreSQL Support
- Full PostgreSQL connector via asyncpg (optional dependency)
- `open-navicat[postgresql]` extras for pip install
- Backup/restore with pg_dump/psql (PGPASSWORD auto-set)
- Schema sync generates PostgreSQL-compatible DDL (double-quote quoting, CREATE INDEX, DROP CONSTRAINT)
- Data sync with PostgreSQL metadata queries (pg_catalog, information_schema)

#### AI Enhancements
- ReAct Agent mode (`ai agent`) — multi-step reasoning with search_schema/generate_sql/execute_sql actions
- Schema RAG (`nl2sql_with_rag`, `ask_with_rag`) — auto-inject table structure into prompts
- Chat history persistence (`save_chat_history`, `load_chat_history`) via SQLite

#### CLI Fixes
- Refactored `backup_cmd` to delegate to BackupService (was reimplementing inline)
- Added `conn close` — disconnect active connection
- Added `schema databases` — list all databases on server
- Added `ai config` — configure AI provider at runtime
- Added `ai test` — test AI connection
- Added `backup delete`, `backup history`, `backup jobs`, `backup job-remove`, `backup job-toggle`

#### Testing
- Integration tests with testcontainers (MySQL 8.0 + PostgreSQL 16)
- 16 integration tests (8 MySQL, 8 PostgreSQL)
- Run with: `poetry run pytest tests/integration/ -v -m integration`

### Removed
- `open_navicat_rs/` (Tauri/Rust version) — may be forked as separate project

[0.2.0]: https://github.com/hackmagic/OpenNavicat/releases/tag/v0.2.0

## [0.1.0] - 2026-07-01

### Added

#### Core
- CLI framework with 31 commands (conn, query, schema, data, backup, ai)
- Async MySQL/MariaDB connector with connection pooling
- SSH tunnel support via paramiko
- AES-GCM password encryption
- Platform-specific config persistence (JSON + SQLite)

#### AI Integration
- Natural language to SQL (`query nl`)
- SQL optimization analysis (`ai optimize`)
- SQL explanation (`ai explain`)
- SQL fix (`ai fix`)
- Interactive data analysis chat (`ai chat`)
- AI schema design (`schema design`)
- Intelligent test data generation (`data generate`)
- Multi-backend support: OpenAI, DeepSeek, Ollama, Custom

#### GUI (PySide6/Qt)
- Object browser with tree navigation and 30+ context menu items
- SQL editor with syntax highlighting, autocomplete, code snippets
- Data viewer with pagination, sorting, filtering, import/export
- Table designer with 8 tabs (fields, indexes, FKs, options, comments, checks, triggers, DDL)
- AI copilot sidebar with multi-mode support
- Backup/restore panel with scheduling
- Schema sync panel with diff visualization
- Data sync panel for row-level synchronization
- BI dashboard with chart rendering
- Model designer with ER diagram (React Flow)
- Object designer for tables/views/routines
- Query manager with save/design functionality
- Scheduler panel for automation jobs
- Data dictionary with HTML export
- Built-in MySQL command line terminal
- Server monitor with auto-refresh
- Query history log
- Data transfer wizard for cross-database copy

#### Settings
- 8-tab settings dialog (General, Tabs, Code Completion, Editor, Records, AI, Auto Recovery, Advanced)
- Editor color customization (6 color schemes)
- AI temperature control with slider
- Auto-recovery settings for queries, models, BI

#### Import/Export
- 7 export formats: CSV, JSON, XML, HTML, SQL, TXT, Excel
- 7 import formats: CSV, JSON, XML, HTML, SQL, TXT, Excel
- Connection import/export via JSON

#### i18n
- Chinese (zh_CN) and English (en_US) support

#### Testing
- 78 unit tests covering AI service, models, config, sync engine, metadata cache, SQL utils

#### Documentation
- Bilingual README (English / 简体中文)
- Contributing guide
- CLI reference manual
- Architecture documentation
- AI module documentation
- Security documentation
- Development guide
- Data flow diagrams
- Deployment guide
- 7 module-specific documentation files

[0.1.0]: https://github.com/hackmagic/OpenNavicat/releases/tag/v0.1.0
