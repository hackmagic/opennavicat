# Changelog

All notable changes to OpenNavicat will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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
