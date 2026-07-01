# 完整数据流设计

> 版本: 0.1.0 | 更新: 2026-06-21

本文档覆盖 OpenNavicat 所有核心操作的数据流，包括 CLI 模式和 GUI 模式。

---

## 1. 连接管理数据流

### 1.1 CLI: 新建并激活连接

```
CLI: opennavicat conn add --name prod --host prod.example.com --test
CLI: opennavicat conn open prod
CLI: opennavicat query run "SELECT 1"
```

```
[conn add]
User CLI ──→ conn_cmd.add_connection()
               ├── ConnectionInfo(name="prod", host="prod.example.com", ...)
               ├── if --test:
               │      connection_manager.connect(info)
               │         ├── ConnectionPool.open(info)
               │         │    ├── SSHTunnel? (skip)
               │         │    └── MySQLConnector.connect()
               │         │         └── aiomysql.create_pool(host, port, user, password)
               │         └── LocalConfigDB.save_connection(info)
               │              └── INSERT INTO connections VALUES (...)
               └── LocalConfigDB.save_connection(info)

[conn open]
User CLI ──→ conn_cmd.open_connection()
               ├── LocalConfigDB.get_connection("prod")
               ├── connection_manager.connect(info)
               │    └── ConnectionPool.open(info) → MySQLConnector.connect()
               └── Console: "✓ Connected to prod.example.com:3306"

[query run]
User CLI ──→ query_cmd.run_sql()
               ├── _get_active_conn() → connection_manager.active_ids[0]
               ├── QueryEngine.execute(conn_id, "SELECT 1")
               │    └── ConnectionPool.get(conn_id) → MySQLConnector
               │         └── cur.execute("SELECT 1") → fetchall()
               └── format_output(rows, "table")
                    └── Rich Table → Console
```

### 1.2 GUI: 连接对话框

```
User → MainWindow._new_connection()
         └── ConnectionDialog.exec()
              ├── User fills form (host/user/password/SSH/SSL)
              ├── [Test Connection] → connection_pool.open(info) → test → close
              └── [OK] → accepts
                   └── MainWindow gets ConnectionInfo
                        └── ObjectBrowser.add_connection(info)
                             ├── QTreeWidgetItem("prod.example.com")
                             └── LocalConfigDB.save_connection(info)
```

---

## 2. SQL 查询数据流

### 2.1 CLI: 执行 SQL

```
User: opennavicat query run "SELECT * FROM users LIMIT 5" --conn prod --format json

query_cmd.run_sql()
  ├── _resolve_conn("prod") → conn_id
  ├── result = QueryEngine.execute(conn_id, "SELECT * FROM users LIMIT 5")
  │    ├── ConnectionPool.get(conn_id) → MySQLConnector
  │    ├── time.perf_counter() → start
  │    ├── cur.execute(sql)
  │    │    ├── description → columns
  │    │    ├── fetchall() → rows
  │    │    └── rowcount / lastrowid
  │    ├── time.perf_counter() → end
  │    └── QueryResult(success, columns, rows, execution_time_ms)
  │
  ├── result.success?
  │    ├── NO  → Console.print("[red]SQL Error: {error}[/red]")
  │    └── YES →
  │         ├── is_select?
  │         │    ├── YES → format_output(rows, "json", title)
  │         │    └── NO  → Console.print("Query OK, N rows affected")
  │         └── Save to query_history
  └── Exit
```

### 2.2 CLI: 自然语言查询

```
User: opennavicat query nl "查询最近7天的注册用户" --conn prod

query_cmd.natural_language_query()
  ├── _resolve_conn("prod") → conn_id
  ├── schema_context = _get_schema_context(conn_id)
  │    └── metadata_service.list_databases() → tables → columns
  │
  ├── sql = ai_service.nl2sql(description, schema_context)
  │    └── _call_llm([
  │         {"role": "system", "content": "You are a SQL expert..."},
  │         {"role": "user", "content": "Schema:\n{ctx}\n\nConvert:\n{desc}"}
  │    ])
  │
  ├── Console.print(Syntax(sql, "sql"))  # 显示生成的 SQL
  ├── result = QueryEngine.execute(conn_id, sql)
  │    └── (同上)
  ├── format_output(rows, "table", title)
  └── Exit
```

### 2.3 GUI: SQL 编辑器

```
User types SQL → Ctrl+Enter

SQLEditorWidget._execute()
  ├── sql = self._editor.toPlainText()
  ├── connector = ConnectionPool.get(self._connection_id)
  ├── result = asyncio.run(connector.execute(sql))
  │    └── (同上，使用 aiomysql)
  └── self._display_result(result)
       ├── success?
       │    ├── YES → 填充 QTableWidget / 状态栏信息
       │    └── NO  → 显示错误信息
       └── self.executed.emit(result)  # 信号
```

---

## 3. 数据浏览数据流

### 3.1 CLI: 分页浏览

```
User: opennavicat data browse mydb.users --limit 100 --offset 0 --order "id DESC"

data_cmd.browse_table()
  ├── sql = "SELECT * FROM `mydb`.`users` ORDER BY id DESC LIMIT 100 OFFSET 0"
  ├── result = QueryEngine.execute(conn_id, sql)
  └── format_output(result.rows, "table", title="mydb.users (100 rows)")
```

### 3.2 GUI: 表双击打开

```
User double-click "users" in ObjectBrowser

ObjectBrowser._open_table(item)
  → parent.parent().open_table_tab(conn_id, "mydb", "users")
    → MainWindow creates TableViewerWidget(conn_id, "mydb", "users")
      → _load_page()
        ├── connector = connection_pool.get(conn_id)
        ├── count_sql: "SELECT COUNT(*) FROM `mydb`.`users`"
        ├── page_sql:  "SELECT * FROM `mydb`.`users` LIMIT 500 OFFSET 0"
        ├── render result into QTableWidget
        └── update pagination info
```

---

## 4. Schema 同步数据流

### 4.1 CLI: 比较差异

```
User: opennavicat schema diff mydb mydb_staging --conn prod

schema_cmd.schema_diff()
  ├── src_tables = metadata_service.list_tables(conn_id, "mydb")
  ├── tgt_tables = metadata_service.list_tables(conn_id, "mydb_staging")
  ├── only_in_src = src_tables - tgt_tables
  ├── only_in_tgt = tgt_tables - src_tables
  ├── common = src_tables & tgt_tables
  │
  ├── diff_rows = []
  │   for t common:
  │       src_cols = get_table_info(conn_id, "mydb", t).columns
  │       tgt_cols = get_table_info(conn_id, "mydb_staging", t).columns
  │       if diff: mark as "Modified"
  │
  └── format_output(diff_rows, "table", "Schema Diff")
```

### 4.2 CLI: 同步

```
User: opennavicat schema sync mydb mydb_staging --conn prod --apply

schema_cmd.schema_sync()
  ├── 同 diff 获取差异
  ├── for each missing table in target:
  │     info = metadata_service.get_table_info(conn_id, "mydb", table)
  │     ddl = generate_create_table(info)
  │     Console.print(ddl)  # 预览
  │
  ├── if --apply:
  │     for each ddl:
  │         QueryEngine.execute(conn_id, ddl)
  │
  └── Console.print("✓ Schema synchronized!")
```

---

## 5. AI 数据流

### 5.1 自然语言→SQL→执行

```
User: opennavicat query nl "每个月的销售额趋势" --conn prod

┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  [User Input]                                                    │
│    "每个月的销售额趋势"                                           │
│       ↓                                                         │
│  [Schema Context Builder]                                        │
│    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE                    │
│    FROM information_schema.COLUMNS                              │
│    WHERE TABLE_SCHEMA = ?                                       │
│       ↓                                                         │
│  [LLM Prompt]                                                    │
│    Schema:                                                      │
│      mydb.orders: id(INT), user_id(INT), total(DECIMAL),        │
│                created_at(DATETIME), status(VARCHAR)            │
│      mydb.products: id(INT), name(VARCHAR), price(DECIMAL)      │
│      ...                                                        │
│    Natural language: "每个月的销售额趋势"                          │
│       ↓                                                         │
│  [LLM Response: SQL]                                             │
│    SELECT DATE_FORMAT(created_at, '%Y-%m') AS month,            │
│           SUM(total) AS revenue                                  │
│    FROM orders                                                   │
│    WHERE status = 'paid'                                         │
│    GROUP BY month                                                │
│    ORDER BY month                                                │
│       ↓                                                         │
│  [Query Engine]                                                  │
│    Execute SQL → QueryResult                                     │
│       ↓                                                         │
│  [Output Formatter]                                              │
│    ┌────────┬─────────┐                                          │
│    │ month  │ revenue │                                          │
│    ├────────┼─────────┤                                          │
│    │ 2026-01│ 152300  │                                          │
│    │ 2026-02│ 178900  │                                          │
│    │ 2026-03│ 165400  │                                          │
│    └────────┴─────────┘                                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 AI Schema Design → Deploy

```
User: opennavicat schema design "博客系统: 用户发文章评论" --deploy --conn prod

┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  [User Input]                                                    │
│    "博客系统: 用户发文章评论"                                       │
│       ↓                                                         │
│  [System Prompt]                                                 │
│    "You are a database architect. Design clean, normalized       │
│     schemas. Use InnoDB, utf8mb4, include PK/FK/indexes."       │
│       ↓                                                         │
│  [LLM Response: DDL]                                             │
│    CREATE TABLE users (                                         │
│      id INT AUTO_INCREMENT PRIMARY KEY,                          │
│      username VARCHAR(50) NOT NULL UNIQUE,                       │
│      email VARCHAR(255) NOT NULL,                                │
│      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP              │
│    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;                      │
│    CREATE TABLE posts (...);                                     │
│    CREATE TABLE comments (...);                                  │
│       ↓                                                         │
│  [Preview]                                                       │
│    Console: Syntax highlighting of DDL                           │
│    Confirm: "Deploy this schema?" (y/N)                          │
│       ↓                                                         │
│  [Execute]                                                       │
│    QueryEngine.execute(conn_id, ddl)                             │
│       ↓                                                         │
│  Console: ✓ Schema deployed!                                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 备份恢复数据流

### 6.1 备份

```
User: opennavicat backup create mydb --output backup.sql --compress

backup_cmd.backup_database()
  ├── Find connection info (host/port/user/password)
  ├── cmd = ["mysqldump", "--host=...", "--port=...", "--user=...",
  │          "--password=...", "--routines", "--triggers", "--events",
  │          "--single-transaction", "mydb"]
  ├── subprocess.run(cmd, stdout=file)
  ├── if compress: gzip file
  └── Console: "✓ Backup completed: backup.sql.gz (123.4 KB)"
```

### 6.2 恢复

```
User: opennavicat backup restore mydb backup.sql --create-db

backup_cmd.restore_database()
  ├── Find connection info
  ├── if --create-db: QueryEngine.execute("CREATE DATABASE IF NOT EXISTS mydb")
  ├── cmd = ["mysql", "--host=...", "--port=...", "--user=...",
  │          "--password=...", "mydb"]
  ├── subprocess.run(cmd, stdin=file)
  └── Console: "✓ Database 'mydb' restored"
```

---

## 7. 数据导入导出数据流

### 7.1 导出

```
User: opennavicat data export mydb.orders --format json --where "status='paid'"

data_cmd.export_data()
  ├── sql = "SELECT * FROM `mydb`.`orders` WHERE status='paid'"
  ├── result = QueryEngine.execute(conn_id, sql)
  ├── Convert rows → [{col: val}, ...]
  ├── Write to file:
  │    json:  json.dump(data, file)
  │    csv:   csv.DictWriter.writerows(data)
  │    excel: openpyxl.Workbook → ws.append(row)
  └── Console: "✓ Exported 500 rows to orders.json"
```

### 7.2 导入

```
User: opennavicat data import mydb.users users.csv --batch-size 500

data_cmd.import_data()
  ├── Load file → list[dict]
  │    csv:   csv.DictReader(file)
  │    json:  json.load(file)
  │    excel: openpyxl.load_workbook()
  ├── for batch in chunks(data, 500):
  │     connector.batch_insert(db, table, batch)
  │     Console: progress "Imported N/M rows..."
  └── Console: "✓ Imported 500 rows into mydb.users"
```
