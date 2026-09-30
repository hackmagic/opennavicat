# `open_navicat.drivers` — 驱动层

引擎注册表、连接器契约与连接串解析。CLI / GUI / 服务层 / 未来的 MCP server 都只面向这一层编程，不直接 import 具体 connector 模块。

## 模块构成

| 文件 | 职责 |
| --- | --- |
| `base_connector.py` | `BaseConnector` 抽象接口 —— 所有引擎必须实现的契约（生命周期 / 元数据 / 查询 / 行级读写） |
| `registry.py` | `DRIVER_REGISTRY`：引擎键 → `DriverSpec`；`get_connector_class()` / `get_spec()` / `is_available()` / `available_engines()` |
| `dsn.py` | `parse_dsn` / `dsn_to_connection` / `info_to_dsn`，DSN 与 `ConnectionInfo` 双向转换 |
| `<engine>_connector.py` | 具体引擎实现 |

`open_navicat/dal/base_connector.py` 与 `open_navicat/dal/*_connector.py` 是兼容 shim，旧导入路径仍可用，但新代码请 import `open_navicat.drivers.*`。

## 当前支持的引擎

`mysql`、`postgresql`、`sqlite`、`duckdb`、`mongodb`、`redis`、`sqlserver`、`clickhouse`、`oracle`（`conn engines` 可查看本机哪些驱动已装好）。

## 接入一个新引擎

只需要两处改动，不需要碰连接池、CLI 或 GUI：

1. 写 `open_navicat/drivers/<engine>_connector.py`，实现 `BaseConnector` 的全部抽象方法。
2. 在 `registry.py` 的 `DRIVER_REGISTRY` 加一行 `DriverSpec`，声明 `default_port` / `module` / `class_name` / `package`，可选装填 `optional` + `pip_extra`，文件型引擎填 `file_based`。

`--engine` 帮助文本、`conn engines`、DSN scheme 与端口默认值、GUI 连接对话框的引擎下拉框都会自动跟上（别名写在 `ENGINE_ALIASES`）。

## 约定与坑

- **`package` 必填**：填第三方包名（import 名，如 `clickhouse_connect`）。留空会让 `is_installed()` 永远返回 `True`——mongodb/redis 曾经就是这样把"驱动未安装"报成"可用"的。
- **驱动缺失要抛 `DriverNotFoundError`**（`ONV-DRV-002`），并在 `connect()` 开头检查模块级 import 是否为 `None`；不要静默 `return False`。
- **`connect()` 失败必须记 `self._last_error`**：`BaseConnector.__init__()` 负责初始化该字段，子类 `__init__` **必须调用 `super().__init__()`**，否则异常路径自身会 `AttributeError` 把真实错误盖掉。
- **同步驱动统一用单线程 executor 桥接**（`sqlserver` / `clickhouse` / `oracle`）。一个 connector 一个 worker 线程：既避开 ODBC/客户端库的线程安全问题，也把"连接被创建线程绑定"这类隐患隔离掉。
- **返回值必须 JSON 可序列化**：`Decimal`、`bytes`、`datetime`、`UUID`、LOB 都在驱动层就地转换，不要留给导出或 AI 层炸。
- **参数绑定形式各引擎不同**：ClickHouse 只支持命名绑定，传位置 tuple 会返回明确错误而不是静默丢弃；Oracle 分页用命名绑定、DML 用位置绑定。
- **懒加载**：注册表按需 import connector 模块，所以未安装的可选驱动不会在包 import 时拖垮整个应用；同理，依赖矩阵里看不到 `<engine>_connector` 的顶层入边是预期行为。
