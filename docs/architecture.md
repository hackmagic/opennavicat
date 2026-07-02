# OpenNavicat 架构设计

> 版本: 0.5.0 | 更新: 2026-07-02

## 1. 设计哲学

```
CLI-First + AI-Native + GUI-Optional
```

| 原则 | 含义 |
|------|------|
| **CLI-First** | 所有功能优先通过 CLI 暴露；GUI 是 CLI 的可视化前端 |
| **AI-Native** | LLM 是一等公民，自然语言是第一查询语言 |
| **API-Driven** | Core Library 是公共 API，CLI / GUI / AI Agent 都调用同一套接口 |
| **Async by Default** | 所有数据库操作异步 (aiomysql/asyncpg)，不阻塞任何接口 |

## 2. 整体架构

```
                         ┌──────────────────────────┐
                         │     AI Agent / LLM       │
                         │  (自然语言 → 操作)        │
                         └──────────┬───────────────┘
                                    │ 调用 CLI 命令
                         ┌──────────▼───────────────┐
                         │        CLI (Typer)        │
                         │  核心交互接口，50+ 子命令   │
                         └──────────┬───────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
    ┌─────────▼──────┐   ┌─────────▼──────┐   ┌─────────▼──────┐
    │    GUI          │   │  Core Library  │   │  CI/CD / 脚本  │
    │  (PySide6)      │   │  (open_navicat)│   │  (GitHub Actions│
    │  可选前端       │   │  所有业务逻辑  │   │   /PyInstaller) │
    └─────────────────┘   └────────┬───────┘   └────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
    ┌─────▼──────┐        ┌───────▼──────┐        ┌───────▼──────┐
    │ Services   │        │  DAL         │        │  Utils       │
    │ 连接管理    │        │ MySQL连接器   │        │ SQL 生成     │
    │ 查询引擎   │        │ PostgreSQL连接│        │ SQL 美化     │
    │ 元数据     │        │ SSH隧道      │        │ 密码加密     │
    │ AI服务     │        │ 本地SQLite   │        │ 输出格式化   │
    │ 备份服务   │        │              │        │              │
    │ 同步引擎   │        │              │        │              │
    │ 调度器     │        │              │        │              │
    └────────────┘        └──────────────┘        └──────────────┘
```

## 3. 核心模块依赖关系

```
main.py
  ├─ cli/app.py          (Typer CLI 入口)
  │   ├─ conn_cmd.py     ──→ services/connection_manager ──→ dal/connection_pool.py
  │   ├─ query_cmd.py    ──→ services/query_engine       ──→ dal/mysql_connector.py
  │   ├─ schema_cmd.py   ──→ services/metadata_service   ──→ dal/mysql_connector.py
  │   ├─ data_cmd.py     ──→ services/query_engine       ──→ dal/mysql_connector.py
  │   ├─ backup_cmd.py   ──→ services/backup_service      ──→ subprocess(mysqldump/pg_dump)
  │   ├─ ai_cmd.py       ──→ services/ai_service          ──→ httpx/OpenAI
  │   ├─ snippet_cmd.py  ──→ dal/local_config              (SQLite snippets table)
  │   └─ cloud_cmd.py    ──→ services/cloud_discovery      (cloud provider APIs)
  │
  └─ app.py              (QApplication, GUI 入口)
      └─ ui/main_window.py
          ├─ ui/widgets/object_browser.py  ──→ services/metadata_service
          ├─ ui/widgets/sql_editor.py      ──→ services/query_engine
          ├─ ui/widgets/table_viewer.py    ──→ services/query_engine
          ├─ ui/dialogs/connection_dialog.py ──→ services/connection_manager
          └─ ui/dialogs/snippet_manager.py   ──→ dal/local_config
```

## 4. 分层职责

### 4.1 UI 层 (open_navicat/ui/)

| 组件 | 职责 | 调用服务 |
|------|------|----------|
| `MainWindow` | 主窗口框架、菜单、Tab 工作区 | — |
| `ObjectBrowser` | 连接树（分组/搜索/拖放）、数据库对象浏览 | `MetadataService`, `local_db` |
| `SQLEditorWidget` | SQL 编辑、执行、结果查看 | `QueryEngine` |
| `TableViewerWidget` | 数据网格/表单视图、分页、编辑、筛选、BLOB 查看 | `QueryEngine` |
| `ConnectionDialog` | 连接编辑表单 | `ConnectionManager` |
| `SnippetManagerDialog` | 代码片段编辑/管理 (CRUD + 变量替换) | `local_db` |
| `BlobViewerDialog` | BLOB 图片/文本/十六进制查看 | — |
| `QueryBuilderWidget` | 可视化拖拽 SQL 查询构建器 | `metadata_service` |
| `QueryCompareDialog` | 并排 SQL 对比 | — |

### 4.2 CLI 层 (open_navicat/cli/)

| 命令组 | 入口文件 | 子命令数 | 说明 |
|--------|----------|----------|------|
| `conn` | `conn_cmd.py` | 12 | list/add/edit/remove/test/open/close/export/import + group list/rename/delete |
| `query` | `query_cmd.py` | 6 | run/file/explain/nl/history/stream |
| `schema` | `schema_cmd.py` | 7 | list/show/create/diff/sync/design + databases |
| `data` | `data_cmd.py` | 4 | browse/export/import/generate |
| `backup` | `backup_cmd.py` | 9 | create/restore/list/schedule/delete/history/jobs/job-remove/job-toggle |
| `ai` | `ai_cmd.py` | 15 | ask/optimize/explain/fix/chat/tables/agent/config/test/chat-history/schema/build/data-quality/anomaly/review |
| `snippet` | `snippet_cmd.py` | 4 | list/add/remove/show |
| `cloud` | `cloud_cmd.py` | 1 | discover |
| `snippet` | `snippet_cmd.py` | 4 | list/add/remove/show |

### 4.3 服务层 (open_navicat/services/)

| 服务 | 职责 | 关键类/方法 |
|------|------|-------------|
| `ConnectionManager` | 连接生命周期 | `connect()`, `disconnect()`, `list_saved()` |
| `QueryEngine` | SQL 执行与解释 + 查询结果缓存 | `execute()`, `explain()`, `explain_format_json()` |
| `QueryCache` | LRU 查询结果缓存 (TTL 60s, max 256) | `get()`, `set()`, `invalidate()` |
| `QueryCache` | LRU 查询结果缓存 (TTL 60s, max 256) | `get()`, `set()`, `invalidate()` |
| `MetadataService` | Schema 信息 | `list_databases()`, `get_table_info()`, `list_tables()` |
| `AIService` | LLM 集成 (含 Function Calling + 多轮 Schema 设计 + 数据质量/异常检测/SQL Review) | `nl2sql()`, `optimize()`, `agent()`, `design_schema_iterative()`, `chat()`, `data_quality()`, `anomaly_detection()`, `sql_review()` |
| `BackupService` | 备份/恢复 | `backup()`, `restore()`, `schedule_backup()` (mysqldump + pg_dump) |
| `SyncEngine` | 结构对比与同步 | `compare_schemas()`, `sync_schema()`, `generate_sync_sql()` (MySQL/PostgreSQL) |
| `DataSyncEngine` | 数据对比与同步 (含增量同步) | `compare_tables()`, `sync_data()`, `generate_sync_script()` (MySQL/PostgreSQL) |
| `AutomationService` | 定时调度 | `add_job()`, `remove_job()`, `list_jobs()` (APScheduler, backup/query/sync) |
| `CloudDiscoveryService` | 云数据库发现 (AWS 存根) | `discover_aws()`, `discover_all()` |

### 4.4 数据访问层 (open_navicat/dal/)

| 模块 | 技术 | 职责 |
|------|------|------|
| `MySQLConnector` | aiomysql | MySQL/MariaDB 异步连接、查询、元数据 |
| `PostgreSQLConnector` | asyncpg | PostgreSQL 异步连接、查询、元数据 |
| `SSHTunnel` | asyncssh | 异步 SSH 隧道 |
| `ConnectionPool` | 内存 | 连接池管理与复用 |
| `LocalConfigDB` | SQLite | 连接配置、设置、片段持久化 |

### 4.5 工具层 (open_navicat/utils/)

| 模块 | 职责 |
|------|------|
| `sql_formatter.py` | SQL 美化、压缩、解析、分类 |
| `sql_generator.py` | DDL/DML 代码生成 |
| `safe_password.py` | 密码 AES-GCM 加密存储 |
| `output_formatter.py` | CLI 输出格式化 (table/json/csv/markdown) |
| `query_cache.py` | LRU 查询结果缓存 (TTL 60s, max 256) |
| `cloud_discovery.py` | 云数据库发现服务 |

## 5. 技术栈

| 维度 | 技术 | 版本 |
|------|------|------|
| 语言 | Python | 3.10+ |
| CLI 框架 | Typer | 0.12+ |
| 终端渲染 | Rich | 13.7+ |
| GUI 框架 | PySide6 (Qt) | 6.5+ |
| MySQL 驱动 | aiomysql + pymysql | 0.2+ / 1.1+ |
| PostgreSQL 驱动 | asyncpg | 0.30+ (可选) |
| SSH 隧道 | asyncssh | 2.17+ |
| SQL 解析 | sqlparse | 0.5+ |
| 加密 | cryptography (Fernet) | 42+ |
| 定时调度 | APScheduler | 3.10+ |
| LLM 后端 | openai + httpx | 1.12+ / 0.27+ |
| HTTP 客户端 | httpx | 0.27+ |
| 打包 | PyInstaller | — |
| 测试 | pytest + pytest-asyncio | 8.0+ / 0.24+ |
| 集成测试 | testcontainers | 4.9+ |

## 6. 设计模式

| 模式 | 使用场景 | 实现 |
|------|----------|------|
| **单例** | 全局服务对象 | `connection_pool`, `connection_manager`, `ai_service` 等模块级实例 |
| **抽象工厂** | 数据库连接器 | `BaseConnector` → `MySQLConnector` / `PostgreSQLConnector` |
| **策略** | AI 提供商切换 | `AIService._call_llm()` 按 `provider` 路由到不同后端 |
| **外观** | 服务层封装 | `ConnectionManager` 包装 `ConnectionPool` + `LocalConfigDB` |
| **适配器** | 输出格式 | `format_output()` 适配 table/json/csv/markdown |
| **命令** | CLI 命令 | Typer 每个子命令独立封装 |
| **模板方法** | 连接器抽象 | `BaseConnector` 定义 `connect()/execute()/get_metadata()` 接口 |

## 7. 扩展性设计

```
数据库扩展: open_navicat/dal/base_connector.py ← SQLiteConnector, MariaDBConnector
AI 提供商扩展: open_navicat/services/ai_service.py ← _call_openai(), _call_ollama(), _call_custom()
输出格式扩展: open_navicat/utils/output_formatter.py ← _print_html(), _print_yaml()
存储后端扩展: open_navicat/dal/local_config.py ← RedisConfigDB, FileConfigDB
备份后端扩展: open_navicat/services/backup_service.py ← xtrabackup, pg_basebackup
同步引擎扩展: open_navicat/services/sync_engine.py ← MariaDB 特定语法
```
