# OpenNavicat Roadmap

> Last updated: 2026-07-06 | Current: v0.7.0 (Beta)

## Vision

**CLI-First, AI-Native** database management tool that makes database operations as natural as conversation and as scriptable as code.

---

## ✅ Released (v0.7.0)

- [x] 3 database engines: MySQL/MariaDB, PostgreSQL, SQLite
- [x] 59+ CLI commands across 9 command groups
- [x] Full GUI (PySide6) with 19 widgets + 7 dialogs
- [x] AI: NL2SQL, query optimization, explain, fix, data generation
- [x] AI: ReAct agent with Schema RAG + chat persistence
- [x] Schema sync & data sync (MySQL ↔ PostgreSQL)
- [x] Backup/restore (mysqldump/pg_dump), scheduled automation
- [x] BI Dashboard, ER Model Designer, Object Designer
- [x] i18n (zh_CN / en_US, 1282 keys)
- [x] 173 unit tests + 16 integration tests + CI/CD
- [x] Multi-platform builds (Win/Mac/Linux, CLI + GUI)

---

## 🔜 Phase 1 — Community Infrastructure (1-2 weeks)

- [ ] Public roadmap + changelog
- [ ] pre-commit hooks for contributors
- [ ] Docker image (automatic push to GHCR/Docker Hub)
- [ ] Feature comparison table vs Navicat/DBeaver/DataGrip

## 🔜 Phase 2 — CLI Experience (2-4 weeks)

- [ ] `opennavicat init` — interactive setup wizard
- [ ] AI API error handling: retry, friendly messages, logging
- [ ] Data masking before LLM submission, Ollama-first privacy docs
- [ ] More install methods (brew, scoop, one-liner)

## 🔜 Phase 3 — GUI ↔ CLI Bridge (4-6 weeks)

- [ ] GUI command panel — real-time CLI command preview for every action
- [ ] Export operation history as `.sh` / `.ps1` scripts
- [ ] End-to-end tutorial: "AI analyze ecommerce DB → generate report"
- [ ] GUI table virtual scrolling (QTableView + custom model)

## 🔜 Phase 4 — AI Deepening (6-8 weeks)

- [ ] Schema RAG v2: vector/keyword retrieval for 5-10 relevant tables
- [ ] Agent safety: dry-run + Y-confirm for DDL/non-SELECT DML
- [ ] sqlglot integration: cross-dialect SQL, AST-level optimization
- [ ] Multi-agent collaboration (Schema Agent / SQL Agent / Report Agent)

---

## 🔮 Future (Long-term)

- Plugin system (Python extension interface)
- DuckDB support (local analytics)
- Git integration (schema versioning, Database as Code)
- Nuitka compilation (smaller binaries, faster startup)

---

## How to influence the roadmap

- [Open an issue](https://github.com/hackmagic/OpenNavicat/issues) with the `enhancement` label
- Vote on existing issues with 👍 reactions
- Submit a PR — see [CONTRIBUTING.md](CONTRIBUTING.md)
