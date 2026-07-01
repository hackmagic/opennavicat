<div align="center">

# OpenNavicat

**CLI-First, AI-Native Database Management Tool**

A free, open-source alternative to Navicat Premium, built with Python.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)
[![Issues](https://img.shields.io/github/issues/hackmagic/OpenNavicat)](https://github.com/hackmagic/OpenNavicat/issues)

[English](#english) | [简体中文](#简体中文)

</div>

---

## English

### What is OpenNavicat?

OpenNavicat is a full-featured database management tool inspired by [Navicat Premium](https://www.navicat.com/). It provides both a **CLI-first** interface and an optional **GUI** (PySide6/Qt), with built-in **AI capabilities** for natural language queries, SQL optimization, and schema design.

### Highlights

- **CLI-First** — Every operation has a CLI command. AI (LLM) can call CLI directly.
- **AI-Native** — Natural language to SQL, query optimization, auto-fix broken SQL, intelligent data generation.
- **Full GUI** — Navicat-like graphical interface with object browser, SQL editor, table designer, data viewer, BI dashboard, and more.
- **Multi-Database** — MySQL/MariaDB + PostgreSQL + SQLite.
- **7 Export Formats** — CSV, JSON, XML, HTML, SQL, TXT, Excel.
- **Open Source** — MIT License. Free for personal and commercial use.

### Quick Start

```bash
# Install
pip install open-navicat

# Add a connection
opennavicat conn add --name prod --host db.example.com --user root --test

# Activate connection
opennavicat conn open prod

# Natural language query
opennavicat query nl "show me the top 10 customers by revenue"

# Execute SQL
opennavicat query run "SELECT COUNT(*) FROM users"

# Launch GUI
opennavicat gui
```

### AI Features

| Command | Description | Example |
|---------|-------------|---------|
| `query nl` | Natural language → SQL → Execute | `query nl "users registered last 7 days"` |
| `ai optimize` | SQL performance analysis | `ai optimize "SELECT * FROM t WHERE YEAR(d)=2026"` |
| `ai explain` | Plain language SQL explanation | `ai explain "SELECT ... LEFT JOIN ..."` |
| `ai fix` | Fix broken SQL queries | `ai fix "SELCT * FORM users"` |
| `ai chat` | Interactive data analysis | `ai chat --conn prod` |
| `ai agent` | ReAct multi-step reasoning | `ai agent "query all active users" --db mydb` |
| `ai config` | Configure AI provider | `ai config --provider deepseek --api-key sk-xxx` |
| `ai test` | Test AI connection | `ai test` |
| `ai chat-history` | View/clear chat history | `ai chat-history show` |
| `schema design` | AI schema design | `schema design "blog: users, posts, comments" --deploy` |
| `data generate` | Intelligent test data | `data generate mydb.users --count 1000` |

### CLI Commands

```
opennavicat
├── conn             Connection management
│   ├── list / add / edit / remove / test / open / close
│
├── query            SQL queries
│   ├── run / file / explain / nl / history
│
├── schema           Schema management
│   ├── databases / list / show / create / diff / sync / design
│
├── data             Data operations
│   ├── browse / export / import / generate
│
├── backup           Backup & restore
│   ├── create / restore / list / delete / history / schedule
│   ├── jobs / job-remove / job-toggle
│
├── ai               AI assistant
│   ├── ask / optimize / explain / fix / chat / tables
│   ├── agent / config / test / chat-history
│
└── gui              Launch GUI (optional)
```

### Tech Stack

| Component | Technology |
|-----------|-----------|
| CLI Framework | Typer + Rich |
| GUI Framework | PySide6 (Qt 6) |
| Database Driver | aiomysql + asyncpg + aiosqlite (async) |
| SSH Tunnel | asyncssh |
| SQL Parser | sqlparse |
| Password Encryption | cryptography (AES-GCM) |
| AI Engine | OpenAI / DeepSeek / Ollama |
| Scheduler | APScheduler |
| Packaging | PyInstaller |

### Documentation

| Document | For | Description |
|----------|-----|-------------|
| [CLI Reference](docs/CLI_REFERENCE.md) | All users | Complete CLI command reference |
| [AI Module](docs/AI_MODULE.md) | Developers | AI architecture, prompts, provider config |
| [Architecture](docs/architecture.md) | Developers | System architecture, module design |
| [Security](docs/SECURITY.md) | Ops/Security | Encryption, transport security |
| [Development Guide](docs/DEVELOPMENT.md) | Contributors | Setup, code standards, testing |
| [Data Flow](docs/DATA_FLOW.md) | Developers | Data flow diagrams |
| [Deployment](docs/DEPLOYMENT.md) | Ops | Packaging, CI/CD, Docker |

### Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

### License

[MIT License](LICENSE) — Free for personal and commercial use.

---

## 简体中文

### 什么是 OpenNavicat？

OpenNavicat 是一款功能齐全的数据库管理工具，灵感来源于 [Navicat Premium](https://www.navicat.com/)。它提供 **CLI 优先** 的操作方式和可选的 **图形界面**（PySide6/Qt），内置 **AI 能力**，支持自然语言查询、SQL 优化和结构设计。

### 核心特性

- **CLI 优先** — 每个操作都有对应的 CLI 命令，AI (LLM) 可直接调用。
- **AI 原生** — 自然语言转 SQL、查询优化、自动修复错误 SQL、智能数据生成。
- **完整 GUI** — 类 Navicat 图形界面，包含对象浏览器、SQL 编辑器、表设计器、数据查看器、BI 看板等。
- **多数据库** — MySQL/MariaDB + PostgreSQL + SQLite。
- **7 种导出格式** — CSV、JSON、XML、HTML、SQL、TXT、Excel。
- **开源免费** — MIT 许可证，个人和商业用途均可免费使用。

### 快速上手

```bash
# 安装
pip install open-navicat

# 添加连接
opennavicat conn add --name prod --host db.example.com --user root --test

# 激活连接
opennavicat conn open prod

# 自然语言查询
opennavicat query nl "上个月每个品类的销售额趋势"

# 执行 SQL
opennavicat query run "SELECT COUNT(*) FROM users"

# 启动图形界面
opennavicat gui
```

### AI 功能

| 命令 | 功能 | 示例 |
|------|------|------|
| `query nl` | 自然语言 → SQL → 执行 | `query nl "最近7天注册用户"` |
| `ai optimize` | SQL 性能分析 | `ai optimize "SELECT * FROM t WHERE YEAR(d)=2026"` |
| `ai explain` | SQL 作用解释 | `ai explain "SELECT ... LEFT JOIN ..."` |
| `ai fix` | 修复报错 SQL | `ai fix "SELCT * FORM users"` |
| `ai chat` | 交互式数据分析 | `ai chat --conn prod` |
| `ai agent` | ReAct 多步推理代理 | `ai agent "查询所有活跃用户" --db mydb` |
| `ai config` | 配置 AI 提供商 | `ai config --provider deepseek --api-key sk-xxx` |
| `ai test` | 测试 AI 连接 | `ai test` |
| `ai chat-history` | 查看/清除聊天历史 | `ai chat-history show` |
| `schema design` | AI 设计表结构 | `schema design "博客系统: 用户、文章、评论" --deploy` |
| `data generate` | 智能生成测试数据 | `data generate mydb.users --count 1000` |

### 技术栈

| 组件 | 技术 |
|------|------|
| CLI 框架 | Typer + Rich |
| GUI 框架 | PySide6 (Qt 6) |
| 数据库驱动 | aiomysql + asyncpg + aiosqlite（异步） |
| SSH 隧道 | asyncssh |
| SQL 解析 | sqlparse |
| 密码加密 | cryptography (AES-GCM) |
| AI 引擎 | OpenAI / DeepSeek / Ollama |
| 定时任务 | APScheduler |
| 打包 | PyInstaller |

### 贡献

欢迎贡献！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)（贡献指南）。

### 许可证

[MIT 许可证](LICENSE) — 个人和商业用途均可免费使用。
