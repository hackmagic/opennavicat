# DBX 源码对比与补开发计划

> 对标仓库：[`t8y2/dbx`](https://github.com/t8y2/dbx)（Apache-2.0 / Rust）
> 本仓库：[`hackmagic/OpenNavicat`](https://github.com/hackmagic/OpenNavicat)（MIT / Python）
> 目的：从**源码结构、能力边界、运行时形态、工程成熟度、生态化程度**五个维度定位差距，给出可执行、可验收的补齐路线。

---

## 0. 基线与复核方法

本文结论基于**实际克隆源码逐项核对**，不是二手转述。

| 项 | DBX | OpenNavicat |
| --- | --- | --- |
| 核对 commit | `497d7c9`（2026-09-29） | `651a42d`（master） |
| 版本 | 滚动发布（README 标注 100+ 数据库 / ~25 MB） | `0.8.0`（见 `open_navicat/__init__.py`） |
| 主语言 | Rust（前端 TypeScript；扩展 Go / JDBC Agent） | Python 3.10+（PySide6 / Typer） |
| 许可 | Apache-2.0 | MIT |
| 社区规模（核对时） | ~21.6k stars / 2.07k forks | ~2 stars |
| 分发形态 | Desktop / Web / Docker / CLI / MCP | CLI / GUI / Docker |

DBX 核对锚点：`README.md`、`crates/ARCHITECTURE.md`、`plugins/README.md`、`packages/mcp-server/README.md`、`docs/backend-error-handling.md`、`plugins/connection-types/`（86 个连接描述）、`plugins/dialects/`（37 个方言）、`agents/drivers/`（约 50 个 Agent 驱动）。

OpenNavicat 核对锚点：`open_navicat/dal/`（`base_connector.py` + 6 个 connector）、`open_navicat/services/`、`open_navicat/plugin/` + `open_navicat/plugins/`、`open_navicat/utils/`、`open_navicat/ui/`、`open_navicat/cli/`。

> 上游是滚动发布，数据会持续变化。建议每季度重跑一次本核对，并更新上表的 commit。

---

## 1. 结论摘要

**DBX 的核心优势不在单点功能，而在"平台化 + 零运行时负担"。**

它是一个可分发的数据库工作台：统一 Rust 底座、多形态入口（Desktop / Web / CLI / MCP）、签名插件平台、超宽数据库覆盖、企业级错误契约与安全治理。

**OpenNavicat 的优势集中在"AI 工作流"与"CLI 优先体验"。**

- 已是 Navicat 风格的客户端 + AI 助手，AI 能力（NL2SQL / 优化 / 解释 / 修复 / ReAct Agent / Schema RAG）在方向上是差异化的。
- 数据库覆盖面、插件生态、跨形态一致性、运行时体积均不及 DBX。

**总体判断：**

- 短期：补齐数据库可见覆盖、统一错误模型、查询链路（超时/取消/流式）、数据网格。
- 中期：建立 Driver / SQL / Core / Platform 分层，做 MCP Server 原型。
- 长期：形成"核心能力 + 扩展生态 + 多端一致性"的数据库工作台。
- **不要试图在短期内复刻 DBX**，尤其是 100+ 数据库覆盖与 Marketplace。

---

## 2. 源码结构对比

### 2.1 DBX 的结构特征

大型 Rust workspace，分层清晰：

- `apps/`：桌面端（Tauri）等前端入口
- `crates/`：核心 Rust 能力（27 个 crate）
- `agents/`：JDBC / Go Agent 驱动扩展
- `packages/`：CLI、MCP、插件 CLI 及多平台二进制
- `plugins/`：插件平台、SDK、签名、连接类型与方言描述
- `deploy/`：Docker / Homebrew / 1Panel / fnOS 等发行
- `docs/`：Next.js 文档站与实施文档

`crates/ARCHITECTURE.md` 定义了明确的依赖方向与所有权：

```text
desktop / web / cli / mcp
            │
         dbx-core
            ├── dbx-drivers ── dbx-sql ── dbx-types
            ├── dbx-plugin-runtime ── dbx-types + dbx-platform
            ├── dbx-ai-provider ── dbx-platform
            ├── dbx-formats
            └── dbx-platform
```

关键约束：**下层 crate 不得反向依赖 core**（含 build / dev 依赖），并由 `scripts/core-architecture.test.mjs` 在 CI 中做架构守卫。这是 DBX 能持续扩张而不腐化的根本原因。

| Crate | 独有实现 |
| --- | --- |
| `dbx-types` | 连接配置、数据库身份、查询与元数据 DTO |
| `dbx-sql` | 解析、方言注册与加载、SQL 风险、DDL/DML、结构差异计划 |
| `dbx-drivers` | 原生驱动、隧道、JDBC/Agent 运行、超时取消、SQLite 元数据 |
| `dbx-formats` | CSV / XLSX / 文本 / ZIP 编码 |
| `dbx-ai-provider` | 模型与 CLI 适配器、流式协议、token 用量 |
| `dbx-plugin-runtime` | manifest、签名与安装、Marketplace、子进程会话 |
| `dbx-platform` | 进程、路径、代理、下载、版本比较 |

### 2.2 OpenNavicat 的结构特征

经典 Python 单体应用：`open_navicat/{cli,services,dal,ui,models,utils,plugin,plugins}`。

优点是易读、上手快、迭代快。弱点是：

- 层间边界弱，`services / dal / ui / cli` 互有渗透
- 数据库连接逻辑、服务逻辑、GUI 逻辑耦合较紧
- 扩展点少（`plugin/` 只有 `BasePlugin` + `manager.py`，无 manifest / 签名 / 权限）
- 多端一致性差
- 没有独立的"核心协议 / 方言 / 驱动"体系

---

## 3. 功能差距对比

### 3.1 数据库覆盖

| 维度 | DBX | OpenNavicat |
| --- | --- | --- |
| 连接目标 | 86 个连接描述文件 + Agent 扩展，README 宣称 100+ | 注册表 9 个 connector：MySQL/MariaDB、PostgreSQL、SQLite、DuckDB、SQL Server、ClickHouse、Oracle、MongoDB、Redis |
| 用户可见 | 全部在 UI / CLI 可选 | README / `--engine` / `conn engines` / GUI 连接对话框均已覆盖 9 个（GUI 下拉框 2026-09-30 起改为读注册表） |
| 扩展方式 | 原生驱动 + JDBC Agent + 插件连接类型 | 注册表一行 `DriverSpec` + 一个 connector 模块（`drivers/registry.py`） |

剩余缺口方向（backlog，非本轮 10 个目标）：Snowflake、Doris、StarRocks、达梦、Gauss 系、KingbaseES、Trino/Presto。SQL Server / ClickHouse / Oracle 已于 Phase 3 补齐。

### 3.2 查询与编辑器

| 能力 | DBX | OpenNavicat |
| --- | --- | --- |
| 编辑器 | CodeMirror 6，9 套主题 | `ui/widgets/sql_editor.py` |
| 补全 | 元数据感知补全 | 已有 information_schema 补全（深度较浅） |
| 执行 | `Cmd+Enter`、选区执行、格式化、诊断 | 执行、选区执行；格式化/诊断较弱 |
| 历史/片段 | 查询历史、SQL 片段、标签恢复、SQL 文件执行 | 有 `query_manager.py` / `snippet_manager.py` |
| 超时/取消 | 支持 | **缺失** |
| 流式 | 支持 | 已有 `query_engine.execute_stream`（未在 GUI 打通） |
| 缓存 | 支持 | 已有 `utils/query_cache.py`（内存 LRU+TTL，无写失效联动） |
| AI 辅助 | 解释/优化/修复 + 安全审查 | NL2SQL/优化/解释/修复（差异化优势） |

### 3.3 数据网格

| 能力 | DBX | OpenNavicat |
| --- | --- | --- |
| 虚拟滚动 | 支持大结果集 | `virtual_table_model.py` 已有骨架 |
| 行内编辑 + 保存前 SQL 预览 | 支持 | **缺失** |
| 过滤/排序/搜索/分页 | DataGrip 风格过滤、全文搜索 | 基础 |
| 导出 | CSV / JSON / Markdown / XLSX / INSERT | 7 种格式（CSV/JSON/XML/HTML/SQL/TXT/Excel） |

### 3.4 Schema / 对象管理

| 能力 | DBX | OpenNavicat |
| --- | --- | --- |
| 对象浏览器 | 表/视图/过程/函数/索引/外键/触发器 + 搜索/固定 | `object_browser.py`（雏形） |
| 表结构编辑器 | 支持（列/索引变更可审阅） | `table_designer.py` |
| ER 图 | 支持 | `ui/widgets/model_designer/` |
| Schema diff | 支持 | `schema_sync_panel.py` |
| Explain plan | 可视化执行计划 | 基础 |
| 字段血缘 | 支持 | **缺失** |
| 跨库对象搜索 | 支持 | **缺失** |

### 3.5 数据操作与迁移

| 能力 | DBX | OpenNavicat |
| --- | --- | --- |
| 导入 | CSV / Excel | `import_export_wizard.py` |
| 迁移 | Data transfer（跨库） | `data_sync_engine.py`（MySQL↔PG） |
| 导出 | 整库 dump | `backup_service.py`（mysqldump/pg_dump） |
| 数据比较 | 支持 | `query_compare_dialog.py` |
| 文件预览 | Parquet / CSV / JSON（DuckDB 驱动） | **缺失** |
| 连接导入 | 支持 DBeaver / Navicat 配置导入 | **缺失** |

### 3.6 专用浏览器与消息中间件

| 能力 | DBX | OpenNavicat |
| --- | --- | --- |
| Redis 专用控制台 | 键模式搜索、批量操作、命令运行、TTL、全数据类型 | 基础 key 浏览 + 命令 |
| MongoDB 专用控制台 | 文档 CRUD + 分页、Atlas/副本集 | 基础 |
| 消息队列 | Kafka / RocketMQ / RabbitMQ / Pulsar 控制台 | **缺失** |
| MQTT | 主题树、订阅、发布 | **缺失** |
| 服务注册/配置 | Nacos / Consul / ZooKeeper / etcd | **缺失** |

> MQ 与中间件控制台是 DBX 区别于"数据库客户端"的重要赛道，但**是否纳入 OpenNavicat 范围需先决策**（见 §5.3）。

### 3.7 AI 与 MCP

| 能力 | DBX | OpenNavicat |
| --- | --- | --- |
| 模型接入 | Claude / OpenAI / Ollama / OpenAI 兼容 | 同类支持 |
| AI SQL 安全审查 | 内建，执行前审查 | **缺失** |
| MCP Server | 独立 Rust 二进制 + npm 包，支持只读/读写/完全访问三档 | **缺失**（仓库内无 MCP 实现） |
| CLI Agent Skill | `dbx agent setup` 离线安装 Skill | **缺失** |

### 3.8 插件生态（差距最大）

| 能力 | DBX | OpenNavicat |
| --- | --- | --- |
| 包格式 | `.dbxp`，manifest v1 + Host API 1.x + sidecar 协议 v1 | 无 |
| 签名 | Ed25519，仓库签名 + 密钥轮换 + 信任模型 | 无 |
| 沙箱 | 插件 UI 子进程沙箱 | 无 |
| SDK | Rust / Go / TypeScript（`sdk/rust`、`sdk/go`、CLI） | 无 |
| 分发 | `t8y2/dbx-store` Marketplace，catalog v1 | 无 |
| 约束 | catalog ≤4 MiB、包 ≤512 MiB、SHA-256 + 大小校验、签名密钥 ID 比对 | 无 |
| 现有基础 | — | `plugin/base.py` + `manager.py` + 2 个内置插件 |

### 3.9 安全与错误契约

| 能力 | DBX | OpenNavicat |
| --- | --- | --- |
| 统一错误对象 | `BackendError` v1（`code / messageKey / messageParams / source / origin / operationOutcome / detail / errorPosition / diagnostics`） | 无（仅有零散异常与 `AIError`） |
| 恢复策略 | `RecoveryPolicy` 依据类型化错误决定保留/隔离 Session | 无 |
| Agent 协议 | Protocol v2 + `structured_error_v1` capability | 无 |
| 凭据加密 | 支持 + 迁移向导 | `utils/safe_password.py`（Fernet + PBKDF2 机器密钥） |
| 脱敏 | 支持 | `utils/data_masker.py` |
| 审计 | 支持 | 部分 |

### 3.10 运行时与分发形态

| 维度 | DBX | OpenNavicat |
| --- | --- | --- |
| 运行时依赖 | 无（无 JRE / 无 venv / 无 Chromium），单文件二进制 | 需 Python + PySide6（GUI 包 ~120 MB） |
| 体积 | ~25 MB | CLI ~15 MB / GUI ~120 MB |
| 形态 | Desktop / Web / Docker / CLI / MCP + 独立二进制 | CLI / GUI / Docker |
| 包管理 | Homebrew / Scoop / WinGet / Flatpak / Nix / npm | pip / install.sh / PyInstaller |
| 自动更新 | 内置 | 无 |

> **这是最难补齐、也最影响"能不能被随手装上"的结构性差距**（见 §8 风险）。

### 3.11 许可与社区

- DBX：Apache-2.0，~21.6k stars。
- OpenNavicat：MIT，~2 stars。
- 两者均为宽松许可。若未来考虑复用 DBX 代码，Apache-2.0 与 MIT 兼容，但必须保留其 `LICENSE` / `NOTICE` 与版权声明，且不得反向声称。

---

## 4. DBX 的核心优势总结

1. **超宽数据库覆盖** —— 不只是"多几个数据库"，而是"统一接入模式 + JDBC/Agent 扩展 + 声明式连接描述"。
2. **平台级插件体系** —— manifest + Ed25519 签名 + 沙箱 + SDK + Marketplace，是从工具走向生态的关键。
3. **Rust 分层架构 + 架构守卫** —— 单向依赖由 CI 强制，可独立测试与演进。
4. **AI + MCP + CLI 一体化** —— 把数据库操作标准化成工具调用，而非"外挂一个聊天框"。
5. **零运行时负担** —— 25 MB 单文件，安装即用。
6. **工程成熟度高** —— 错误契约、恢复策略、迁移加密、供应链安全都成体系。

---

## 5. OpenNavicat 应补齐的方向

### 5.1 优先补齐（基础盘）

数据库可见覆盖 → 统一错误模型 → 查询链路（超时/取消/流式）→ 数据网格 → MCP → 插件 MVP。

### 5.2 保持差异化，不必照抄

- Python 生态与更快的迭代速度
- AI-first 的工作流（ReAct、Schema RAG、数据质量）
- CLI-first + GUI 可选
- 更轻的开发门槛

### 5.3 范围决策（已定，2026-09-29）

| 问题 | 决策 | 影响 |
| --- | --- | --- |
| 是否进入消息队列 / 中间件赛道 | **暂不进入** | 不追 Kafka / RocketMQ / RabbitMQ / Pulsar / MQTT / Nacos / Consul 等 |
| 数据库覆盖目标 | **收敛到 10 个高价值引擎** | 不追 100+；优先 SQL Server → ClickHouse → Oracle |
| Python 运行时体积 | **独立立项**（Phase 9） | 不阻塞 Phase 0–8；CLI 必须保持无 Qt |

> DBX 源码只作逻辑参考，不复制实现。以上三项是本项目自己的范围取舍，后续改动需同步更新本表。

---

## 6. 补足开发计划

> 顺序：先骨架 → 再覆盖面 → 再生态。

### Phase 0：基线固化与依赖盘点 — **已完成（2026-09-29）**

- import 图扫描落地为 `scripts/build_dependency_matrix.py`，产出 `docs/module_dependency_matrix.md`（自动生成，不手改）。
  - 结果：**209 条顶层导入边，0 条违反分层**。
  - 扫描规则：只算顶层导入；函数内延迟导入（插件扩展点）与 `TYPE_CHECKING` 守卫内的导入不计入耦合——这两类是合法的软依赖。
- 暴露测试基线缺口：未装 `pytest-asyncio` 时是 243 passed / 62 skipped，装上后 **289 passed / 16 skipped**。那 46 个"skip"其实是**根本没被执行的 async 测试**，原先的覆盖率是虚高的。

**验收：** 依赖矩阵产出 ✅；async 测试缺口暴露 ✅；文档入库待提交 ⏳。

### Phase 1：统一错误模型 + 分层骨架 — **已完成（2026-09-29）**

- **`open_navicat/errors.py`**（新增）：`NavicatError` 统一错误对象，字段 `code / message_key / detail / source / stage / recoverable / retryable`。`to_dict()` 输出稳定 JSON，供 CLI / GUI / MCP 复用同一错误身份，而不是各自编字符串。
  - 稳定错误码：`ONV-CNN-001..003`（连接 / 连接丢失 / SSH）、`ONV-DRV-001..002`（引擎不支持 / 驱动缺失）、`ONV-QRY-001..003`（查询失败 / 超时 / 取消）、`ONV-SQL-001`、`ONV-AI-001..002`、`ONV-PLG-001`、`ONV-CFG-001`。
  - `redact()` 构造时自动脱敏：`password=` / `token=` / DSN 的 `user:pass@` / `bearer <token>` 全部打码——**错误落日志前就不可能带凭据**。
  - `NavicatError.from_exception()` 做类型化映射（`TimeoutError→ONV-QRY-002`、`ImportError→ONV-DRV-002`、`ConnectionError→ONV-CNN-001`、`SyntaxError→ONV-SQL-001`）；stage 为 `connect` 时落到连接类。
  - `AIError` / `AITransientError` 保留原名，定义挪到 `errors.py`，`services/ai_service.py` 只再导出——`except AIError` 的 20 处调用点零改动。
- **`open_navicat/drivers/`**（新增）：`base_connector.py` + `registry.py`（`DriverSpec` / `DRIVER_REGISTRY` / `get_connector_class()` / `get_spec()` / `SUPPORTED_ENGINES` / `ENGINE_ALIASES` / `available_engines()`）。
  - **`ConnectionPool.open()` 的 `if/elif` 引擎分支已删除**，改为注册表查表。顺带修掉一个隐性 bug：以前未知引擎会**静默回落到 MySQL**。现在报 `ONV-DRV-001` 并列出支持的引擎。
  - `dal/base_connector.py` 保留兼容 shim；connector 改为 `from open_navicat.drivers.base_connector import`。
  - 6 个 connector 把 `connect()` 里被吞掉的原始异常记到 `BaseConnector._last_error`（新增 `last_error` 属性），不再只是 `return False`——**"连不上"从此有原因**。
- **CLI 结构化错误**：`conn add --test` / `conn test` 失败时打印错误码 + 说明 + `source/stage/recoverable/retryable`。

**验收：** 全量 `pytest` **371 passed / 16 skipped**（基线 243），零回归 ✅；CLI 结构化错误 ✅；`dal` 旧路径可导入 ✅。

**未完成（留到 Phase 3）：** 6 个 connector 实体仍住在 `open_navicat/dal/`，只有 `BaseConnector` 迁到了 `drivers/`。真正迁移后要同步改 `registry.py` 的模块路径。

### Phase 2：查询链路（超时 / 取消 / 流式 / 缓存）— **部分完成（2026-09-29）**

- **查询超时** ✅：`QueryEngine.execute(..., timeout=秒)`，超时抛 `ONV-QRY-002`（`retryable=True`）。
- **连接超时** ✅：`ConnectionPool.open()` 用 `asyncio.wait_for` 强制 `connect_timeout`，不再只靠驱动自己守时——超时明确报 `timed out after 2s`。
- **查询取消** ✅：`CancelToken`（线程安全）+ `submit()` / `cancel(query_id)` / `result()` / `cancel_all()` / `running_queries`，给 GUI 留出不阻塞事件循环的入口；取消抛 `ONV-QRY-003`（`recoverable=True`）。
  - 实现要点：查询与取消触发器用 `asyncio.wait(FIRST_COMPLETED)` **显式竞速**。**不要**用"嵌套 `ensure_future` + 直接 await 协程"——外层 `Task.cancel()` 会卡在内层任务后面，取消永远传不下去（已实测踩坑，表现为 `run_until_complete` 死等）。
  - 后台查询也要走同一个 `CancelToken`，不要改成 `task.cancel()`，否则又回到上面那个坑。
- **写操作缓存失效** ✅：`is_write()` 识别 15 个变更动词，写操作执行前 `query_cache.invalidate(connection_id)`，且不再把写结果写进读缓存。
- **流式** ⚠️ 仍是占位：`execute_stream()` 只是把已有结果切 chunk，不是真正的服务端游标；GUI 的 `virtual_table_model.py` 虚拟滚动未接。

**验收：** 超时 ✅、取消 ✅、缓存失效 ✅ 各有单测（`tests/unit/test_query_budget.py` 23 例）；GUI 虚拟滚动 ⏳ 未做。

### Phase 3：数据库覆盖 — **已完成（2026-09-30）**

1. **DuckDB 用户可见** ✅ —— `--engine` 列表、`conn engines`、`conn add/test --dsn duckdb:///...` 全部打通；`conn test duckdb:///path` 实测可连。
2. **SQL Server** ✅ —— 新增 `open_navicat/drivers/sqlserver_connector.py`（pyodbc + 单线程 executor 桥接成 async）。
   - 自动挑选 ODBC 驱动（18 → 17 → 13 → Native Client → legacy "SQL Server"），一个都没有时报 `ONV-DRV-002` 并说明去哪装。
   - `Encrypt=` 跟随 `use_ssl`；因为 pyodbc 没有可移植的 CA 参数，`TrustServerCertificate=yes`（已在代码注释里标为待改进）。
   - 返回值统一 JSON 化：`Decimal→float`、`bytes→hex`、`datetime/date/time→isoformat`、`UUID→str`。
   - 41 个单测（mock pyodbc，无需真库）。
3. **ClickHouse** ✅（2026-09-30）—— `open_navicat/drivers/clickhouse_connector.py`：`clickhouse-connect` 走 HTTP 接口（默认 8123，`?ssl=on` → 8443/secure），同样用单线程 executor 桥接成 async。
   - 元数据读 `system.databases / tables / columns / table_indexes`；`Nullable(T)` / `LowCardinality(T)` 会解包出裸类型。
   - **参数只支持命名绑定**：传位置 tuple 会直接返回明确错误，而不是被静默丢弃（丢弃会改变查询语义）。
   - ClickHouse 没有 FK 约束，`foreign_keys` 恒为空；行内编辑走 `ALTER TABLE ... UPDATE/DELETE` mutation，不能参数绑定，因此值经类型化字面量转义后内联。
   - 34 个单测（mock clickhouse_connect，无需真库）。
4. **Oracle** ✅（2026-09-30）—— `open_navicat/drivers/oracle_connector.py`：`python-oracledb` **Thin 模式**（无需本机 Oracle Client），同样 executor 桥接为 async；选同步 API 而非 `oracledb.Async` 是为了 Thin/Thick 行为一致、且与其它桥接驱动的 mock 测试保持同构。
   - DSN 由 `makedsn(host, port, service_name=…)` 生成，无 service 时退化为 `host:port`；网络超时按毫秒换算 `tcp_connect_timeout`。
   - "database" 在 Oracle 语义下映射为 schema/owner（`all_users`），未指定库时用登录用户名大写作为 owner。
   - `DatabaseLOB` 在连接仍打开时读取；隐藏嵌套列（`column_id IS NULL`）跳过。
   - 分页用 12c+ 的 `OFFSET :n ROWS FETCH NEXT :m ROWS ONLY` 命名绑定；DML 用位置绑定。
   - 34 个单测（mock oracledb，无需真库）。
5. **连接串解析** ✅ —— 新增 `open_navicat/drivers/dsn.py`：`parse_dsn` / `dsn_to_connection` / `info_to_dsn`；`conn add --dsn`、`conn test <dsn>`、`conn open <dsn>` 均已接线。支持 scheme 别名（`pg`/`mssql`/`ch`/`sql-server`）、百分号编码凭据、IPv6、query options（`charset`/`ssl`/`pool_min`/`pool_max`/`connect_timeout`）、以及 sqlite/duckdb 的三种路径写法。54 个单测。
6. **connector 实体迁入 `drivers/`** ✅ —— Phase 1 的欠账还清了：6 个 connector 用 `git mv` 迁到 `open_navicat/drivers/`，`dal/*_connector.py` 退化为兼容 shim，旧导入路径仍可用。
7. **GUI 连接对话框接注册表** ✅（2026-09-30）—— `ui/dialogs/connection_dialog.py` 的引擎下拉框不再写死，改为遍历 `DRIVER_REGISTRY` 生成；i18n 缺键时回落 `DriverSpec.display_name`。
   - 切引擎时的端口/字段启用逻辑同步改为注册表驱动：端口取 `spec.default_port`，文件型引擎用 `is_file_engine()` 判定（duckdb 与 sqlite 一致禁用 host/port/user/password），并给 duckdb 的 database 字段加了文件路径 placeholder。
   - "测试连接"失败时展示结构化错误 `NavicatError.render()`（错误码 + 已脱敏说明），不再只有一句 "Connection failed"。
   - "复制 URI" 改走 `info_to_dsn(include_password=True)`，与 `conn test <dsn>` 同源，文件型引擎不再拼出 `sqlite://root@127.0.0.1:3306/path` 这种废串。
8. **依赖与 extras** ✅ —— `pyproject.toml` 补齐并注册 `sqlserver` / `clickhouse` / `oracle` 三个 extra（此前计划文档写了 extra，但 `pyproject.toml` 里根本没有声明），并重新 `poetry lock`。

**顺带修掉 4 个真 bug（都不是新引入的）：**

- **保存的连接丢失 engine**：`connections` 表根本没有 `engine` 列，任何 postgres/mongo/redis/sqlite 配置存下来再读回来都变成 `mysql`。已加列 + 迁移 + 读写，并补了 legacy 库迁移测试。
- **`conn test <dsn>` 会持久化**：`ConnectionManager.connect()` 无条件写库，临时 DSN 被存进用户配置。已加 `persist=False`。
- **`is_installed()` 查错对象**：检查的是内部模块名而不是第三方包，`mongodb`/`redis` 标了 `optional` 却永远返回"可用"。已加 `DriverSpec.package` 字段并修正。
- **DuckDB 的 `connect()` 异常路径自身崩溃**：`DuckDBConnector.__init__` 从未调用 `super().__init__()`，`_last_error` 不存在，一旦连接失败就抛 `AttributeError` 把真实错误盖掉。已补 `super().__init__()`。

**验收：** 全量 `pytest` **556 passed**（Phase 3 上一轮 480），零回归 ✅；`conn engines` 正确列出 9 个引擎并区分 ready / driver missing ✅；`conn test clickhouse://…` 未装驱动时报 `ONV-DRV-002` 并给出 pip 提示 ✅；依赖矩阵 234 条边、0 违规 ✅。

**Phase 3 遗留（已知，非本轮范围）：** 新引擎的真库集成测试需要 CI 容器；`docs/` 里 SQL Server 的 `TrustServerCertificate=yes` 待改为可 pin CA；`data_transfer` / `server_monitor` / `user_manager` 等面板仍按 `getattr(info,"engine","mysql")` 回落，属各功能域自身范围。


### Phase 4：数据网格（2–3 周）

- 行内编辑 + 保存前 SQL 预览（`ui/widgets/table_viewer.py`）。
- 列过滤、排序、搜索、固定列、分页。

**验收：** 只读连接禁止写；预览 SQL 与实际执行 SQL 一致。

### Phase 5：Schema / 对象工作台（2 周）

- 统一对象浏览器（表/视图/存储过程/函数/索引/触发器/约束 + 搜索）。
- DDL diff 可视化 + dry-run（在 `schema_sync_panel.py` 基础上扩展）。

**验收：** diff 可预览、可导出、可 dry-run。

### Phase 6：导入导出 / 迁移流水线（2–3 周）

- 统一 import / export / migrate 抽象；文件预览（CSV / Parquet / JSON / Excel）。
- 大文件流式处理；任务进度与错误汇总。

**验收：** 大文件不 OOM；失败可回滚。

### Phase 7：AI 安全 + MCP Server 原型（2–3 周）

- AI 生成 SQL 执行前安全审查（只读 / 安全写 / 高风险写三档）。
- `open_navicat/mcp/` 原型：`list connections`、`list databases`、`describe table`、`execute query`、`open session`。

**验收：** MCP 工具可被 Claude / Cursor 调用；写操作需确认或 dry-run。

### Phase 8：插件平台 MVP（3–4 周）

- manifest（id / version / permissions）+ loader + 生命周期，在 `plugin/base.py` 上扩展。
- 插件包格式、依赖冲突检测、Ed25519 签名校验。

**验收：** 至少 1 个外部示例插件可安装 / 启用 / 禁用 / 卸载。

### Phase 9：分发与体积（持续）

- 评估 Nuitka 或裁剪 GUI 体积；保证 CLI standalone 不依赖 Qt。
- 增加 brew / scoop / winget 渠道；增加自动更新与完整性校验。

**验收：** CLI 独立包 < 30 MB。

---

## 7. 优先级与排期建议

| 优先级 | 内容 | 建议周期 |
| --- | --- | --- |
| P0 | Phase 0 / 1 / 2 | 0–6 周 |
| P1 | Phase 3（DuckDB 可见化 + SQL Server/ClickHouse）、Phase 4、Phase 7 | 6 周–3 个月 |
| P2 | Phase 5、Phase 6、Phase 8 原型 | 3–6 个月 |
| P3 | Phase 9、插件商店、字段血缘、MQ 控制台 | 6 个月+ |

**当前位置（2026-09-30）：** Phase 0–1 完成；Phase 2 只剩 GUI 虚拟滚动 + 真服务端游标；Phase 3 完成（9 个引擎，含 ClickHouse / Oracle，GUI 下拉框已接注册表）。下一批：Phase 7 MCP Server 原型 + Phase 4 数据网格。

---

## 8. 风险与取舍

1. **体积与运行时是最难补的差距。** Python + PySide6 与 25 MB Rust 单文件不在同一量级，短期只能缓解（Nuitka、分离 CLI 包），无法追平。
2. **插件生态是长周期工程。** 半年内现实目标只能是"能装第三方插件"，不是 Marketplace。
3. **数据库覆盖不要摊大饼。** 追数量会拖垮维护，建议以"高价值 10 个引擎"为阶段目标。
4. **架构守卫必须先行。** 若不在 CI 里加依赖方向检查，分层会在 3 个月内腐化回单体。**已落地（2026-09-30）**：`scripts/build_dependency_matrix.py --check` 同时校验"有低层→高层的违规"和"`docs/module_dependency_matrix.md` 是否与代码同步"，任一不满足即退出码 1，已加入 `.github/workflows/ci.yml`（在 lint 之后、测试之前）。
5. **合规提醒。** 参考 DBX（Apache-2.0）时保留许可与声明；不要复制其专有品牌资产与商店目录。

---

## 9. 与 `dbx_requirements.md` 的关系

- 本文件回答"差在哪、怎么补、先后顺序"。
- `docs/dbx_requirements.md` 回答"每条需求的可验收标准"。
- 两者需同步维护：本文件变更范围或优先级时，同步更新需求文档的验收清单。

## 参考来源

- `dbx/README.md`、`dbx/README.zh-CN.md`
- `dbx/crates/ARCHITECTURE.md`
- `dbx/plugins/README.md`、`plugins/manifest.schema.json`、`plugins/marketplace.schema.json`、`plugins/SIGNING.md`
- `dbx/packages/mcp-server/README.md`、`packages/cli/README.md`
- `dbx/docs/backend-error-handling.md`、`dbx/docs/data-security-migration.md`
- `dbx/plugins/connection-types/`、`dbx/plugins/dialects/`、`dbx/agents/drivers/`
- `OpenNavicat/README.md`、`OpenNavicat/docs/architecture.md`、`OpenNavicat/ROADMAP.md`
- `OpenNavicat/open_navicat/{dal,services,ui,cli,plugin,utils}/`
