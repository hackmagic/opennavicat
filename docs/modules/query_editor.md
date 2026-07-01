# SQL 查询编辑器模块详细设计

> 模块: sql_editor / query_engine / sql_formatter

## 1. 功能描述

提供完整的 SQL 编辑、执行、结果查看体验，支持 CLI 和 GUI 双模式。CLI 模式是主交互方式，GUI 模式是可视化等效。

## 2. 功能矩阵

### 2.1 CLI 模式 (query 命令组)

| 子命令 | 说明 | AI 增强 |
|--------|------|---------|
| `query run` | 执行原始 SQL | — |
| `query file` | 执行 SQL 文件 | — |
| `query explain` | 执行计划分析 | — |
| `query nl` | 自然语言→SQL→执行 | ✅ LLM 生成 SQL |
| `query history` | 查看历史查询 | — |

### 2.2 GUI 模式 (SQLEditorWidget)

| 功能 | 状态 | 实现 |
|------|------|------|
| 语法高亮 | ✅ | QSyntaxHighlighter |
| SQL 美化 | ✅ | sqlparse.format() |
| 多语句执行 | ✅ | sqlparse.split() |
| 结果表格 | ✅ | QTableWidget |
| 执行时间/行数 | ✅ | 状态栏 |
| 自动补全 | 🔄 计划 | information_schema 表/列 |
| 代码片段 | 🔄 计划 | SQLite 存储 |
| 查询构建器 | 📋 计划 | 拖拽可视化 |
| 结果引脚 | 📋 计划 | 固定结果标签 |

### 2.3 核心差异

| 维度 | CLI 模式 | GUI 模式 |
|------|---------|----------|
| 交互方式 | 命令行参数 + stdin | 键盘 + 鼠标 |
| 结果展示 | Rich 表格 / JSON / CSV | QTableWidget |
| 管道友好 | ✅ `\| jq` `\| wc -l` | ❌ |
| CI/CD 集成 | ✅ `opennavicat query run "SQL"` | ❌ |
| AI Agent 调用 | ✅ LLM 可直接调用 | ❌ |

## 3. 查询执行流程

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  CLI/GUI      │    │  QueryEngine │    │  MySQLConn   │
│  query run    │───→│  .execute()  │───→│  .execute()  │
│  query nl     │    │  .explain()  │    │              │
│  sql_editor   │    │  .count()    │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
                           │                    │
                           ▼                    ▼
                    ┌──────────────┐    ┌──────────────┐
                    │ SQL 格式化   │    │  aiomysql    │
                    │ sqlparse     │    │  cur.execute │
                    │ 美化/拆分    │    │  fetchall()  │
                    └──────────────┘    └──────────────┘
```

## 4. 类设计

### QueryEngine (services/query_engine.py)

核心方法:

```python
def execute(connection_id, sql) -> QueryResult
    """执行单条 SQL，返回结构化结果"""
    connector = connection_pool.get(connection_id)
    loop = asyncio.new_event_loop()
    return loop.run_until_complete(connector.execute(sql))

def execute_script(connection_id, script) -> list[QueryResult]
    """拆分多语句脚本并逐条执行"""
    for stmt in sqlparse.split(script):
        results.append(self.execute(connection_id, stmt))

def explain(connection_id, sql) -> QueryResult
    """EXPLAIN 执行计划"""
    return self.execute(connection_id, f"EXPLAIN {sql}")

def explain_format_json(connection_id, sql) -> QueryResult
    """JSON 格式执行计划"""
    return self.execute(connection_id, f"EXPLAIN FORMAT=JSON {sql}")
```

### QueryResult (models/query_result.py)

```python
@dataclass
class QueryResult:
    success: bool
    error_message: str
    columns: list[ColumnMeta]    # SELECT 结果列
    rows: list[list]             # 数据行
    row_count: int
    affected_rows: int           # INSERT/UPDATE/DELETE
    insert_id: int | None
    execution_time_ms: float
    plan: str                    # EXPLAIN 输出
    warnings: list[str]
```

## 5. NL→SQL 数据流

```
用户: "查询最近30天销售额前10的商品"

    │
    ▼
query_cmd.natural_language_query()
    │
    ├── 1. Schema Context 构建
    │     metadata_service.list_databases(conn_id)
    │     metadata_service.list_tables(conn_id, db)
    │     metadata_service.get_table_info(conn_id, db, table)
    │     → "mydb.products: id(INT), name(VARCHAR), price(DECIMAL)
    │        mydb.orders: id(INT), product_id(INT), quantity(INT),
    │                     total(DECIMAL), created_at(DATETIME)"
    │
    ├── 2. LLM Prompt
    │     System: "You are a SQL expert. Generate clean, correct SQL."
    │     User:   "Schema:\n{ctx}\n\nConvert:\n{query}\n\nReturn ONLY SQL."
    │
    ├── 3. LLM Response
    │     → "SELECT p.name, SUM(o.total) AS revenue
    │        FROM products p JOIN orders o ON p.id = o.product_id
    │        WHERE o.created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
    │        GROUP BY p.id ORDER BY revenue DESC LIMIT 10"
    │
    ├── 4. Execute
    │     QueryEngine.execute(conn_id, sql)
    │
    └── 5. Display
          format_output(rows, "table", "Top 10 Products (30 days)")
```

## 6. SQL 美化 (sql_formatter.py)

| 功能 | 函数 | 说明 |
|------|------|------|
| 美化 | `beautify(sql)` | 缩进 + 关键字大写 |
| 压缩 | `minify(sql)` | 去除多余空格，紧凑输出 |
| 提取表名 | `extract_table_names(sql)` | 解析 FROM/JOIN/INTO |
| 拆分语句 | `split_statements(sql)` | 按 `;` 分割 |
| 判断类型 | `is_select()/is_ddl()/is_dml()` | SQL 类型检测 |

## 7. 执行引擎性能

| 场景 | 延迟 | 说明 |
|------|------|------|
| `SELECT 1` | < 5ms | 连接池复用 |
| 简单查询 (100行) | 5-50ms | 取决于网络 |
| 复杂查询 (10万行) | 100ms-5s | 取决于 DB 性能 |
| EXPLAIN | < 20ms | 不扫描数据 |
| 数据导出 (10万行) | 1-10s | 序列化 + 写入文件 |

## 8. 未来扩展

- **AI 查询构建器**: "帮我建一个查询: 本月每个城市的订单量"
- **查询结果缓存**: 相同 SQL 短时间复用结果
- **流式结果**: 超大结果集分批输出 (CLI 模式)
- **查询对比**: 并排比较两个查询结果
- **SQL Review**: AI 审查 SQL 安全性和性能
