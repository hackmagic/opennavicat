# OpenNavicat 补足需求文档（对标 DBX）

> 对标仓库：`t8y2/dbx`  
> 本仓库：`hackmagic/OpenNavicat`  
> 目标：把 OpenNavicat 从“单体工具”升级为“可扩展、可安全分发、AI/CLI/MCP 一致的核心平台”。

---

## 0. 文档说明

### 0.0 对标基线与修订记录

本文的对标结论基于实际拉取 `t8y2/dbx` 源码核对：

| 项 | DBX | OpenNavicat |
| --- | --- | --- |
| 核对 commit | `497d7c9`（2026-09-29） | `651a42d`（master, v0.8.0） |
| 许可 | Apache-2.0 | MIT |
| 主语言 | Rust | Python 3.10+ |

修订记录：
- 2026-09：按上述 commit 复核；修正包名、补充"运行时体积""专用浏览器与消息中间件""连接配置导入"等遗漏需求；标注已有实现，避免重复立项。


### 0.1 目标
这份文档把前面的差距分析拆成**可执行需求**，并给出**验收标准**。

### 0.2 非目标
- 不要求一次性复刻 DBX 的全部功能。
- 不要求改变主语言或放弃 Python。
- 不要求一步到位做插件商店、Marketplace、供应链体系。

### 0.3 范围决策（2026-09-29 已定）

| 事项 | 决策 | 本轮是否写验收标准 |
| --- | --- | --- |
| 消息队列与中间件控制台（Kafka / RocketMQ / RabbitMQ / Pulsar / MQTT / Nacos / Consul / ZooKeeper / etcd） | **不进入** | 否 |
| 数据库覆盖规模 | **收敛到高价值 10 个引擎**，不追 100+ | 是（见 §3.2） |
| 插件 Marketplace / 插件商店 | 本轮不做 | 否 |
| 多语言插件 SDK（Rust / Go） | 本轮不做 | 否 |
| 内置自动更新与包管理器全渠道 | 本轮不做 | 否 |
| Python 运行时体积 | **独立立项**（Phase 9），不阻塞 Phase 0–8 | 是（见 §11.2） |

> DBX 源码只作逻辑参考，不复制实现。

### 0.4 统一验收原则
所有需求默认遵循以下通用验收标准：

1. **功能正确性**：核心路径可稳定运行，无明显回归。
2. **可测试性**：至少包含单元测试；涉及跨层行为时补集成测试。
3. **可观测性**：关键操作有结构化日志或诊断输出。
4. **可恢复性**：失败时有明确错误信息，必要时支持重试/回滚。
5. **向后兼容**：除非明确说明，不得破坏现有 CLI/GUI 行为。
6. **安全优先**：涉及凭据、SQL、插件、远程执行时必须经过安全检查。

---

## 1. 总体架构需求

### 1.1 需求描述
建立分层核心，把当前散落在 `services / dal / ui / cli / utils` 中的能力收敛到清晰边界。

### 1.2 目标结构
建议抽象为以下模块：

- `open_navicat.types`：连接模型、结果模型、错误模型、DTO
- `open_navicat.sql`：SQL 解析、方言识别、风险识别、格式化
- `open_navicat.drivers`：数据库连接器、SSH、连接池、驱动适配
- `open_navicat.formats`：CSV / JSON / Excel / Markdown / SQL export
- `open_navicat.ai`：provider、prompt、agent、safety guard
- `open_navicat.platform`：路径、配置、加密、进程、通知、宿主集成
- `open_navicat.plugins`：插件生命周期、manifest、签名、加载器

### 1.3 验收标准
- [x] 现有 CLI、GUI 主流程仍可用。
- [x] 核心模块之间不出现反向依赖 —— `docs/module_dependency_matrix.md`（`scripts/build_dependency_matrix.py` 自动生成），234 条顶层导入边、0 违规（2026-09-30，含 ClickHouse / Oracle 驱动）。
- [x] 至少 1 个连接器迁移到新分层 —— 全部 9 个 connector 现居 `open_navicat/drivers/`，`dal/base_connector.py` 与 `dal/*_connector.py` 保留兼容 shim。
- [x] 已落地的新模块有模块说明 —— `open_navicat/drivers/README.md`（职责表、接入新引擎的两步流程、`package` 必填 / `super().__init__()` / 单线程 executor 桥接等约定与坑）。`types / sql / formats / platform` 尚未成模块，待各自 Phase 落地时补。
- [x] 至少 1 个 CLI 命令、1 个 GUI 调用路径迁移到新分层 —— CLI：`conn engines|add|test|open` 全走注册表 + `dsn.py`；GUI：`connection_dialog.py` 的引擎下拉框 / 端口默认值 / 测试错误展示改走 `drivers.registry` 与 `drivers.dsn`。
- [ ] 新增模块的单元测试覆盖率不低于项目当前基线（基线：289 passed / 16 skipped，装 `pytest-asyncio` 前是 243/62；当前 **556 passed**）。

---

## 2. 统一错误模型需求

### 2.1 需求描述
引入统一错误对象，替代各处零散字符串异常。

### 2.2 目标结构
错误对象至少包含：

- `code`
- `messageKey`
- `detail`
- `source`
- `stage`
- `recoverable`
- `retryable`

### 2.3 验收标准
- [x] 连接失败、超时、SQL 错误、AI 错误均使用统一错误对象（`open_navicat/errors.py`）；插件错误 `ONV-PLG-001` 已定义，待 Phase 8 接入。
- [x] CLI 展示结构化错误（`conn add --test` / `conn test`）；GUI 连接对话框"测试连接"失败时展示 `NavicatError.render()`（错误码 + 脱敏说明）。
- [x] 错误码保持稳定，不复用、不改义（`ONV-<域>-<序号>`，见 `ERROR_CATALOG` 常量表）。
- [ ] 至少 1 类错误支持本地化展示。
- [x] 错误信息可安全脱敏，不泄露密码、token、连接串（`redact()`，`to_dict()` 输出同样脱敏）。
- [x] 可恢复性字段可用：`ONV-QRY-002`/`ONV-QRY-003` 标 `retryable`/`recoverable`，便于上层做自动重试与重新打开连接。

---

## 3. 数据库驱动扩展需求

### 3.1 需求描述
扩展数据库覆盖，并建立统一驱动适配层。

### 3.2 优先级（目标 10 个引擎）

| 序 | 引擎 | 状态 | 接入方式 |
| --- | --- | --- | --- |
| 1 | MySQL / MariaDB | 已有 | `aiomysql`，基础依赖 |
| 2 | PostgreSQL | 已有 | `asyncpg`，extra `postgresql` |
| 3 | SQLite | 已有 | `aiosqlite`，基础依赖 |
| 4 | MongoDB | 已有 | `motor`，extra `mongodb` |
| 5 | Redis | 已有 | `redis`，extra `redis` |
| 6 | **DuckDB** | ✅ **已暴露** | `duckdb` 基础依赖；`conn add/test --dsn duckdb:///…` |
| 7 | **SQL Server** | ✅ **已实现** | `pyodbc` + 本机 ODBC 驱动，extra `sqlserver` |
| 8 | **ClickHouse** | ✅ **已实现** | `clickhouse-connect`，extra `clickhouse`（HTTP 8123 / HTTPS 8443） |
| 9 | **Oracle** | ✅ **已实现** | `python-oracledb` Thin 模式，extra `oracle`（无需本机 Client） |
| 10 | 待定（按用户反馈） | — | — |

Trino / Presto、国产数据库（达梦 / GaussDB / KingbaseES）**不在本轮 10 个内**，有明确需求再进 backlog。

接入一个新引擎现在是**一处注册表 + 一个 connector 模块**：在 `open_navicat/drivers/registry.py` 的 `DRIVER_REGISTRY` 加一行 `DriverSpec`（含 `package`、`optional`、`file_based`），再写 `open_navicat/drivers/<engine>_connector.py`。CLI、DSN、`conn engines` 会自动跟上。

### 3.3 验收标准
- [x] 新增驱动统一实现 `BaseConnector` 兼容接口（SQL Server / ClickHouse / Oracle 已实现全部抽象方法）。
- [x] 新增驱动可被 CLI、核心服务共同复用（经 `get_connector_class()` 查表；GUI 连接对话框下拉框已改为遍历注册表）。
- [x] 新增驱动具备：连接测试、查询执行、基础元数据读取。
- [x] 驱动失败时有结构化错误返回（`ONV-DRV-002` 驱动缺失 / `ONV-CNN-001` 连接失败 + 原始 ODBC / ORA 诊断）。
- [x] ClickHouse / Oracle 各 34 个 mock 单测，全量单测 **556 passed**（2026-09-30）。
- [ ] 每种驱动至少 1 个集成测试用例 —— SQL Server / ClickHouse / Oracle 目前只有 mock 单测；真库集成测试需要 CI 里的容器。

### 3.4 连接串（DSN）

- [x] `parse_dsn` / `dsn_to_connection` / `info_to_dsn`，见 `open_navicat/drivers/dsn.py`。
- [x] `conn add --dsn`、`conn test <dsn>`、`conn open <dsn>` 均已接线。
- [x] scheme 别名（`pg` / `mssql` / `sql-server` / `mariadb`…）与分隔符容错。
- [x] 百分号编码凭据、IPv6 主机、query options（`charset`/`ssl`/`pool_min`/`pool_max`/`connect_timeout`）。
- [x] 文件型引擎路径（`sqlite:///abs`、`sqlite:////abs`、`sqlite:rel`、`duckdb:///:memory:`）。
- [x] 未知 scheme → `ONV-DRV-001`；畸形 URL → `ONV-CFG-001`；两个方向都能往返。

---

## 4. 查询执行与结果处理需求

### 4.1 需求描述
增强查询执行链路，支持取消、超时、流式返回和结果分页。

### 4.2 验收标准
- [x] 支持查询超时控制（`QueryEngine.execute(..., timeout=秒)` → `ONV-QRY-002`）。
- [x] 支持取消查询（`CancelToken` + `submit()` / `cancel()` / `result()` / `cancel_all()` → `ONV-QRY-003`）。
- [x] 支持结果缓存命中与失效策略（写操作前 `query_cache.invalidate(connection_id)`，识别 15 个变更动词）。
- [x] 查询失败时能定位到可理解的错误阶段（`source` / `stage` 字段，`to_dict()` 可落日志）。
- [x] 连接超时有明确错误（`ConnectionPool.open()` 强制 `connect_timeout`）。
- [ ] 支持大结果集分页或流式读取 —— `execute_stream` 仍是占位实现（切 chunk，非服务端游标），GUI 未打通。
- [ ] 查询执行结果在 CLI 和 GUI 中表现一致。

**实现要点（踩坑记录）：** 查询与取消触发器要用 `asyncio.wait(FIRST_COMPLETED)` 显式竞速。**不要**用"嵌套 `ensure_future` + 直接 await 协程"——外层 `Task.cancel()` 会卡在内层任务后面，取消永远传不下去，`run_until_complete` 死等。后台查询也必须走同一个 `CancelToken`。

---

## 5. 数据网格需求

### 5.1 需求描述
把表查看从基础展示升级为可操作的数据工作台。

### 5.2 验收标准
- [ ] 支持行内编辑。
- [ ] 支持保存前 SQL 预览。
- [ ] 支持列过滤、排序、搜索。
- [ ] 支持分页浏览。
- [ ] 支持大结果集虚拟滚动。
- [ ] 支持导出当前视图数据。

---

## 6. Schema / 对象管理需求

### 6.1 需求描述
构建统一对象浏览器与结构管理能力。

### 6.2 验收标准
- [ ] 支持表、视图、存储过程、函数、索引、触发器、约束统一浏览。
- [ ] 支持对象搜索。
- [ ] 支持 DDL diff 可视化。
- [ ] 支持 schema 变更生成和预览。
- [ ] 支持结构变更回滚或 dry-run。
- [ ] 支持跨库对象搜索。

---

## 7. 数据迁移与导入导出需求

### 7.1 需求描述
把导入导出、迁移、同步统一成可编排的工作流。

### 7.2 验收标准
- [ ] 支持批量导入导出。
- [ ] 支持跨库数据迁移。
- [ ] 支持增量同步。
- [ ] 支持大文件流式处理。
- [ ] 支持迁移前预览与回滚。
- [ ] 支持任务进度和错误汇总。
- [ ] 支持文件预览（CSV / Parquet / JSON / Excel）。
- [ ] 支持连接配置导入（DBeaver / Navicat 导出格式）—— **前置能力已具备**：DBeaver/Navicat 的 JDBC URL 与 DSN 同构，可直接喂给 `parse_dsn()`；待做的是文件解析与字段映射。

---

## 8. AI 与 MCP 标准化需求

### 8.1 需求描述
把 AI 能力从“功能点”升级为“可调用协议”。

### 8.2 验收标准
- [ ] 提供 MCP Server 原型。
- [ ] 至少包含以下工具：
  - list connections
  - list databases
  - describe table
  - execute query
  - open session
  - execute redis command
- [ ] 支持只读 / 安全写 / 高风险写 三种策略。
- [ ] 写操作支持确认或 dry-run。
- [ ] AI 结果包含可追踪的上下文来源。
- [ ] AI 调用链路与本地 CLI / GUI 解耦，可独立测试。

---

## 9. 插件生态需求

### 9.1 需求描述
建立最小可行插件平台，先支撑扩展，再扩展到商店与签名分发。

### 9.2 最小插件模型
插件必须支持：

- manifest
- 插件 ID / 版本 / 权限
- 加载生命周期
- 插件包格式
- 签名校验
- 插件命令扩展点
- 数据源扩展点
- UI 容器（如后续支持）

### 9.3 验收标准
- [ ] 支持插件发现与加载。
- [ ] 支持插件卸载与禁用。
- [ ] 支持插件权限声明。
- [ ] 支持签名校验。
- [ ] 支持至少 1 个外部插件示例。
- [ ] 支持插件依赖冲突检测。
- [ ] 定义插件包格式与 manifest schema（参考 DBX manifest v1，但不必照抄）。
- [ ] 支持插件日志与错误上报。

---

## 10. 安全、加密与审计需求

### 10.1 需求描述
建立凭据、密钥、数据迁移和审计的统一安全模型。

### 10.2 验收标准
- [ ] 凭据加密存储。
- [ ] 支持密钥迁移。
- [ ] 支持敏感字段脱敏。
- [ ] 支持审计日志记录关键操作。
- [ ] 支持失败操作的恢复策略。
- [ ] 支持安全提示和确认。
- [ ] 支持离线或受控环境部署时的安全降级说明。

---

## 11. 分发与安装需求

### 11.1 需求描述
让 OpenNavicat 支持更多运行形态。

### 11.2 验收标准
- [ ] 支持 CLI standalone。
- [ ] 支持 GUI standalone。
- [ ] 支持 Docker / Web 形态。
- [ ] 支持 MCP 形态。
- [ ] 支持自动更新。
- [ ] 支持签名校验和完整性检查。
- [ ] 支持常见包管理渠道接入（brew / scoop / winget / flatpak）。
- [ ] CLI 独立包不依赖 Qt，体积 < 30 MB。
- [ ] 给出 GUI 体积削减方案与实测数据（Nuitka / Qt 模块裁剪）。

---

## 12. 工程化与文档需求

### 12.1 需求描述
补齐架构、接口、安全、插件、MCP 等工程文档。

### 12.2 验收标准
- [ ] 有架构说明文档。
- [ ] 有接口契约文档。
- [ ] 有插件开发文档。
- [ ] 有 MCP 文档。
- [ ] 有安全文档。
- [ ] 有错误码文档。
- [x] CI/CD 覆盖新增模块 —— `.github/workflows/ci.yml` 新增"架构守卫"步骤：`python scripts/build_dependency_matrix.py --check`，分层违规或矩阵文档过期都会让 CI 失败（2026-09-30）。
- [ ] 文档可被新成员快速阅读并执行。

---

## 13. 优先级建议

### P0（2026-09-30 状态）
1. ~~统一错误模型~~ ✅ `open_navicat/errors.py`
2. ~~分层核心骨架~~ ✅ `open_navicat/drivers/`（`BaseConnector` + `registry.py`，连接池引擎分支已删）
3. ~~查询取消 / 超时~~ ✅ `CancelToken` + `timeout=`（取消为 `asyncio.wait` 显竞速，勿用嵌套 `ensure_future`）
4. ~~数据库驱动扩展骨架~~ ✅ 注册表查表 + 连接串解析（`drivers/dsn.py`）

**下一批 P0：** 暂无 —— P0 四条已全部收口，后续按 P1 推进。

### P1（2026-09-30 状态）
1. ~~DuckDB / SQL Server / ClickHouse / Oracle 支持~~ ✅（ClickHouse、Oracle 于 2026-09-30 完成；GUI 连接对话框引擎下拉框已接注册表）
2. MCP Server 原型 —— 未开始
3. Schema diff 可视化 —— 未开始
4. 数据网格增强 —— 未开始

**下一步 P1：** MCP Server 原型（Phase 7）→ 数据网格（Phase 4）→ Schema 工作台（Phase 5）。

### P2
1. 插件平台 MVP
2. 签名与权限
3. 字段血缘
4. 多形态分发

### P3
1. 插件商店 / Marketplace
2. 多语言插件 SDK
3. 企业级审计与合规
4. 更宽数据库覆盖

---

## 14. 交付物清单

### 14.1 文档交付物
- 架构重构说明
- 错误码字典
- MCP 工具列表
- 插件 manifest 规范
- 安全与审计说明
- 分发说明

### 14.2 代码交付物
- 新分层核心包
- 新驱动适配层
- MCP Server 原型
- 插件加载器
- 查询取消/超时实现
- 结构化错误对象

### 14.3 测试交付物
- 单元测试
- 集成测试
- 架构回归测试
- 安全边界测试

---

## 15. 参考来源

DBX（核对 commit `497d7c9`）：
- `dbx/README.md`
- `dbx/crates/ARCHITECTURE.md`
- `dbx/plugins/README.md`、`plugins/manifest.schema.json`、`plugins/marketplace.schema.json`、`plugins/SIGNING.md`
- `dbx/packages/mcp-server/README.md`、`packages/cli/README.md`
- `dbx/docs/backend-error-handling.md`、`dbx/docs/data-security-migration.md`
- `dbx/plugins/connection-types/`、`dbx/plugins/dialects/`、`dbx/agents/drivers/`

OpenNavicat：
- `OpenNavicat/README.md`
- `OpenNavicat/docs/architecture.md`
- `OpenNavicat/docs/dbx_comparison_plan.md`
- `OpenNavicat/open_navicat/{dal,services,ui,cli,plugin,utils}/`
