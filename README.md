<div align="center">

# OpenNavicat

**CLI-First, AI-Native Database Management Tool**

A free, open-source alternative to Navicat Premium, built with Python.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)
[![Issues](https://img.shields.io/github/issues/hackmagic/OpenNavicat)](https://github.com/hackmagic/OpenNavicat/issues)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

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
- **Multi-Database** — MySQL/MariaDB + PostgreSQL + SQLite + MongoDB + Redis.
- **7 Export Formats** — CSV, JSON, XML, HTML, SQL, TXT, Excel.
- **Privacy-First** — Data masking for AI requests. Full offline mode with Ollama. Encrypted credential storage.
- **Open Source** — MIT License. Free for personal and commercial use.

### Comparison

| Feature | OpenNavicat | Navicat Premium | DBeaver EE | DataGrip |
|---------|:-----------:|:---------------:|:----------:|:--------:|
| **Price** | **Free** (MIT) | $599/yr | $299/yr | $199/yr |
| **CLI-First** | ✅ Native | ❌ | ❌ (`dbeaver-cli` limited) | ❌ |
| **AI-Native** (NL2SQL, optimize, fix) | ✅ Built-in | ✅ (paid add-on) | ❌ | 🟡 (AI Assistant) |
| **ReAct Agent** | ✅ Multi-step | ❌ | ❌ | ❌ |
| **Schema RAG** | ✅ Vector/keyword | ❌ | ❌ | ❌ |
| **Cross-Platform** | ✅ Win/Mac/Linux | ✅ Win/Mac | ✅ Win/Mac/Linux | ✅ Win/Mac/Linux |
| **MySQL / PG / SQLite** | ✅ | ✅ | ✅ | ✅ |
| **MongoDB / Redis** | ✅ | ✅ | ✅ | ✅ |
| **BI Dashboard** | ✅ Built-in (no ext libs) | ✅ | ❌ | ❌ |
| **ER Model Designer** | ✅ Conceptual/Logical/Physical | ✅ | ✅ | ✅ |
| **Schema & Data Sync** | ✅ MySQL↔PG | ✅ | ✅ | ❌ |
| **Scheduled Automation** | ✅ (APScheduler) | ✅ | ❌ | ❌ |
| **SSH Tunnel** | ✅ (asyncssh) | ✅ | ✅ | ✅ |
| **i18n** | ✅ zh_CN / en_US | ✅ 10+ langs | ✅ 20+ langs | ✅ 15+ langs |
| **CLI ↔ GUI Bridge** | 🚧 Planned | ❌ | ❌ | ❌ |
| **Plugin System** | 🔮 Future | ❌ | ✅ | ✅ |
| **Open Source** | ✅ MIT | ❌ Proprietary | 🟡 (Community edition) | ❌ Proprietary |
| **Docker Image** | ✅ ghcr.io | ❌ | ❌ | ❌ |

### Quick Start

**One-liner** (auto-downloads latest CLI for your platform):

```bash
# Linux/macOS
curl -fsSL https://github.com/hackmagic/OpenNavicat/releases/latest/download/install.sh | bash

# Windows (PowerShell)
iwr -Uri https://github.com/hackmagic/OpenNavicat/releases/latest/download/install.ps1 | iex
```

**Install via pip** (recommended — includes both CLI and GUI):

```bash
pip install open-navicat
```

**Or use Docker** (CLI only, lightweight):

```bash
docker run --rm ghcr.io/hackmagic/opennavicat:latest conn list
```

**Or download standalone executables** from [Releases](https://github.com/hackmagic/OpenNavicat/releases):

| Package | Platform | Description | Size |
|---------|----------|-------------|------|
| `opennavicat-cli-*` | Win/Mac/Linux | CLI only (no Qt) | ~15 MB |
| `opennavicat-*` | Win/Mac/Linux | Full GUI with PySide6 | ~120 MB |

> **Package managers:** If you'd like to see OpenNavicat on [Homebrew](https://brew.sh), [Scoop](https://scoop.sh), or [Chocolatey](https://chocolatey.org), upvote or open an issue on GitHub!

```bash
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
| Database Driver | aiomysql + asyncpg + aiosqlite + motor + redis.asyncio (async) |
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
| [Privacy](docs/PRIVACY.md) | All users | Data sent to AI, data masking, Ollama offline setup |
| [Tutorials](docs/tutorials/README.md) | All users | End-to-end walkthroughs |
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
- **多数据库** — MySQL/MariaDB + PostgreSQL + SQLite + MongoDB + Redis。
- **7 种导出格式** — CSV、JSON、XML、HTML、SQL、TXT、Excel。
- **隐私优先** — AI 请求自动脱敏，支持 Ollama 全离线模式，凭据加密存储。
- **开源免费** — MIT 许可证，个人和商业用途均可免费使用。

### 功能对比

| 特性 | OpenNavicat | Navicat Premium | DBeaver EE | DataGrip |
|------|:-----------:|:---------------:|:----------:|:--------:|
| **价格** | **免费** (MIT) | $599/年 | $299/年 | $199/年 |
| **CLI 优先** | ✅ 原生支持 | ❌ | ❌ (`dbeaver-cli` 有限) | ❌ |
| **AI 原生** (NL2SQL、优化、修复) | ✅ 内置 | ✅ (付费附加) | ❌ | 🟡 (AI Assistant) |
| **ReAct Agent** | ✅ 多步推理 | ❌ | ❌ | ❌ |
| **Schema RAG** | ✅ 向量/关键词 | ❌ | ❌ | ❌ |
| **跨平台** | ✅ Win/Mac/Linux | ✅ Win/Mac | ✅ Win/Mac/Linux | ✅ Win/Mac/Linux |
| **MySQL / PG / SQLite** | ✅ | ✅ | ✅ | ✅ |
| **MongoDB / Redis** | ✅ | ✅ | ✅ | ✅ |
| **BI 看板** | ✅ 内置 (零外部库) | ✅ | ❌ | ❌ |
| **ER 模型设计器** | ✅ 概念/逻辑/物理 | ✅ | ✅ | ✅ |
| **结构 & 数据同步** | ✅ MySQL↔PG | ✅ | ✅ | ❌ |
| **定时自动化** | ✅ (APScheduler) | ✅ | ❌ | ❌ |
| **SSH 隧道** | ✅ (asyncssh) | ✅ | ✅ | ✅ |
| **国际化** | ✅ 中/英 | ✅ 10+ 语言 | ✅ 20+ 语言 | ✅ 15+ 语言 |
| **CLI ↔ GUI 联动** | 🚧 规划中 | ❌ | ❌ | ❌ |
| **插件系统** | 🔮 未来计划 | ❌ | ✅ | ✅ |
| **开源** | ✅ MIT | ❌ 专有 | 🟡 (社区版) | ❌ 专有 |
| **Docker 镜像** | ✅ ghcr.io | ❌ | ❌ | ❌ |

### 快速上手

**一行命令安装**（自动下载最新版 CLI）：

```bash
# Linux/macOS
curl -fsSL https://github.com/hackmagic/OpenNavicat/releases/latest/download/install.sh | bash

# Windows (PowerShell)
iwr -Uri https://github.com/hackmagic/OpenNavicat/releases/latest/download/install.ps1 | iex
```

**pip 安装**（推荐，包含 CLI 和 GUI）：

```bash
pip install open-navicat
```

**或用 Docker**（纯 CLI，轻量）：

```bash
docker run --rm ghcr.io/hackmagic/opennavicat:latest conn list
```

**或下载独立可执行文件** — 从 [Releases](https://github.com/hackmagic/OpenNavicat/releases) 获取：

| 包 | 平台 | 说明 | 体积 |
|----|------|------|------|
| `opennavicat-cli-*` | Win/Mac/Linux | 纯 CLI，不含 Qt | ~15 MB |
| `opennavicat-*` | Win/Mac/Linux | 完整 GUI + PySide6 | ~120 MB |

```bash
# 添加连接
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

### 文档

| 文档 | 适合 | 内容 |
|------|------|------|
| [CLI 参考手册](docs/CLI_REFERENCE.md) | 所有用户 | 全部 CLI 命令参考 |
| [AI 模块设计](docs/AI_MODULE.md) | 开发者 | AI 架构、Prompt、提供商配置 |
| [架构设计](docs/architecture.md) | 开发者 | 系统架构 |
| [安全设计](docs/SECURITY.md) | 运维/安全 | 加密、传输安全 |
| [隐私保护](docs/PRIVACY.md) | 所有用户 | AI 数据范围、脱敏、Ollama 离线方案 |
| [开发指南](docs/DEVELOPMENT.md) | 贡献者 | 环境搭建、代码规范、测试 |
| [部署指南](docs/DEPLOYMENT.md) | 运维 | 安装、打包、CI/CD、Docker |

### 技术栈

| 组件 | 技术 |
|------|------|
| CLI 框架 | Typer + Rich |
| GUI 框架 | PySide6 (Qt 6) |
| 数据库驱动 | aiomysql + asyncpg + aiosqlite + motor + redis.asyncio（异步） |
| SSH 隧道 | asyncssh |
| SQL 解析 | sqlparse |
| 密码加密 | cryptography (AES-GCM) |
| AI 引擎 | OpenAI / DeepSeek / Ollama |
| 定时任务 | APScheduler |
| 打包 | PyInstaller |

> **⚠️ Windows 用户请注意**
> OpenNavicat 是开源免费软件，暂未购买 EV 代码签名证书。首次运行 GUI 时 Windows SmartScreen 可能弹出 **"Windows 已保护你的电脑"** 警告。请点击 **"更多信息" → "仍要运行"** 放行。源码完全公开，请放心使用。

### 贡献

欢迎贡献！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)（贡献指南）。

### 许可证

[MIT 许可证](LICENSE) — 个人和商业用途均可免费使用。
