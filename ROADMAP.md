# OpenNavicat Roadmap

> Last updated: 2026-10-18 | Current: v0.9.0

## Vision

**CLI-First, AI-Native** database management tool that makes database operations as natural as conversation and as scriptable as code.

---

## ✅ Released (v0.9.0)

- [x] 9 database engines: MySQL/MariaDB, PostgreSQL, SQLite, DuckDB,
      SQL Server, ClickHouse, Oracle, MongoDB, Redis
- [x] 79 CLI commands across 12 command groups + `init` wizard + `ask` alias
- [x] Full GUI (PySide6) with 19 widgets + 7 dialogs
- [x] AI: NL2SQL, query optimization, explain, fix, data generation
- [x] AI: ReAct agent with Schema RAG + chat persistence
- [x] Schema sync & data sync, migration pipeline with dry-run planning
- [x] Backup/restore (mysqldump/pg_dump), scheduled automation
- [x] BI Dashboard, ER Model Designer, Object Designer
- [x] Streaming import (CSV, TSV, JSON, JSONL, XLSX, Parquet) and export
      (CSV, TSV, JSON, Markdown, XLSX, SQL)
- [x] Plugin platform MVP with signed `.onvpkg` packages
- [x] MCP server (`opennavicat mcp serve`) behind the `[mcp]` extra
- [x] i18n (zh_CN / en_US, 1383 keys)
- [x] 1456 unit tests + 16 integration tests + CI/CD on Python 3.11–3.14
- [x] Multi-platform builds (Win/Mac/Linux, CLI + GUI)

### Earlier releases

- v0.8.0 — Phase 6 core experience: filter panel, transactions, cell editor,
  SQL editor folding, extra import formats, data generator, auto-recovery
- v0.7.0 — 3 engines, 59+ CLI commands, AI features, BI/ER/object designers

---

## 🔜 Phase 1 — Community Infrastructure (1-2 weeks)

- [ ] Public roadmap + changelog
- [ ] pre-commit hooks for contributors
- [x] Docker image (automatic push to GHCR/Docker Hub)
- [ ] Feature comparison table vs Navicat/DBeaver/DataGrip

## 🔜 Phase 2 — CLI Experience (2-4 weeks)

- [x] `opennavicat init` — interactive setup wizard
- [x] AI API error handling: retry, friendly messages, logging
- [x] Data masking before LLM submission, Ollama-first privacy docs
- [ ] More install methods (brew, scoop, one-liner)

## 🔜 Phase 3 — GUI ↔ CLI Bridge (4-6 weeks)

- [ ] GUI command panel — real-time CLI command preview for every action
- [ ] Export operation history as `.sh` / `.ps1` scripts
- [ ] End-to-end tutorial: "AI analyze ecommerce DB → generate report"
- [ ] GUI table virtual scrolling (QTableView + custom model)

## 🔜 Phase 4 — AI Deepening (6-8 weeks)

- [ ] Schema RAG v2: vector/keyword retrieval for 5-10 relevant tables
- [x] Agent safety: dry-run + Y-confirm for DDL/non-SELECT DML
- [x] sqlglot integration: cross-dialect SQL, AST-level optimization
- [ ] Multi-agent collaboration (Schema Agent / SQL Agent / Report Agent)

---

## 🔮 Future (Long-term)

- [x] Plugin system (Python extension interface)
- [x] DuckDB support (local analytics)
- [ ] Git integration (schema versioning, Database as Code)
- [ ] Nuitka compilation (smaller binaries, faster startup)

---

## How to influence the roadmap

- [Open an issue](https://github.com/hackmagic/OpenNavicat/issues) with the `enhancement` label
- Vote on existing issues with 👍 reactions
- Submit a PR — see [CONTRIBUTING.md](CONTRIBUTING.md)
