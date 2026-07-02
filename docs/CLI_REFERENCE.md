# OpenNavicat CLI 参考手册

> 版本: 0.5.0 | 命令总数: 51+

`opennavicat` 是 CLI-First 设计，所有功能通过命令行暴露。GUI 只是可选的可视化包装。

## 使用方法

```bash
opennavicat [OPTIONS] COMMAND [ARGS]...

# 全局选项:
#   --version, -v   显示版本
#   --help          显示帮助

# GUI 模式:
opennavicat gui

# CLI 模式 (默认):
opennavicat conn list
opennavicat query run "SELECT * FROM users"
```

---

## 1. conn — 连接管理

```bash
opennavicat conn list            # 列出所有保存的连接
opennavicat conn add             # 新增连接
opennavicat conn edit            # 编辑连接
opennavicat conn remove          # 删除连接
opennavicat conn test            # 测试连接
opennavicat conn open            # 激活连接 (供后续命令使用)
opennavicat conn close           # 关闭连接
opennavicat conn export          # 导出连接到 JSON
opennavicat conn import          # 从 JSON 导入连接
opennavicat conn group list      # 列出连接组
opennavicat conn group rename    # 重命名连接组
opennavicat conn group delete    # 删除连接组
```

### 1.1 conn list

```bash
opennavicat conn list [--format table|json|csv]
```

列出所有已保存的连接配置。

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--format`, `-f` | str | table | 输出格式 |

### 1.2 conn add

```bash
opennavicat conn add \
  --name "Production DB" \
  --host prod.example.com \
  --port 3306 \
  --user admin \
  --password \
  --database mydb \
  --charset utf8mb4 \
  [--ssh-host bastion.example.com] \
  [--ssh-port 22] \
  [--ssh-user jump] \
  [--ssh-password] \
  [--ssh-key ~/.ssh/id_rsa] \
  [--test]
```

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--name`, `-n` | str | **必填** | 连接名称 |
| `--host`, `-h` | str | 127.0.0.1 | 数据库主机 |
| `--port`, `-p` | int | 3306 | 数据库端口 |
| `--user`, `-u` | str | root | 用户名 |
| `--password`, `-P` | str | '' | 密码 (隐藏输入) |
| `--database`, `-d` | str | '' | 默认数据库 |
| `--charset`, `-c` | str | utf8mb4 | 字符集 |
| `--ssh-host` | str | '' | SSH 隧道主机 |
| `--ssh-port` | int | 22 | SSH 隧道端口 |
| `--ssh-user` | str | '' | SSH 用户 |
| `--ssh-password` | str | '' | SSH 密码 |
| `--ssh-key` | str | '' | SSH 私钥路径 |
| `--test`, `-t` | bool | False | 保存前测试连接 |

### 1.3 conn edit

```bash
opennavicat conn edit "Production DB" --name "Prod DB" --host new-host.com
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | str | **必填** 要编辑的连接名称 |
| `--name`, `-n` | str | 新名称 |
| `--host`, `-h` | str | 新主机 |
| `--port`, `-p` | int | 新端口 |
| `--user`, `-u` | str | 新用户名 |
| `--password`, `-P` | str | 新密码 |
| `--database`, `-d` | str | 新默认数据库 |

### 1.4 conn remove

```bash
opennavicat conn remove "Production DB" [--force]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | str | **必填** 连接名称 |
| `--force`, `-f` | bool | False | 强制删除（不确认） |

### 1.5 conn test

```bash
opennavicat conn test "Production DB"
```

测试已保存连接的可用性。

### 1.6 conn open

```bash
opennavicat conn open "Production DB"
```

激活连接。激活后后续的 query/schema/data 命令不需要再指定 `--conn`。

### 1.7 conn close

```bash
opennavicat conn close          # 关闭当前激活连接
opennavicat conn close "Prod"   # 关闭指定连接
```

关闭活跃连接。省略名称时关闭第一个激活的连接。

### 1.8 conn export

```bash
opennavicat conn export "MyDB"              # 导出到 MyDB.json
opennavicat conn export "MyDB" --output /path/to/config.json
```

将连接配置导出为 JSON 文件。导出的文件包含所有连接字段（含分组信息），可通过 `conn import` 恢复。

### 1.9 conn import

```bash
opennavicat conn import /path/to/config.json           # 导入连接
opennavicat conn import /path/to/config.json --test     # 导入前测试连接
```

从 JSON 文件导入连接配置。使用 `--test` 可以在保存前测试连接是否可用。

### 1.10 conn group — 连接组管理

```bash
opennavicat conn group list                # 列出所有连接组及连接数
opennavicat conn group rename "Old" "New"  # 重命名连接组
opennavicat conn group delete "GroupName"  # 删除连接组（连接不丢失）
```

连接组用于在 GUI 对象浏览器中对连接进行分类管理。删除组时，组内的连接不会丢失，只是回到"未分组"状态。

---

## 2. query — SQL 查询

```bash
opennavicat query run         # 执行 SQL
opennavicat query file        # 执行 SQL 文件
opennavicat query explain     # 执行计划分析
opennavicat query nl          # 自然语言→SQL→执行
opennavicat query history     # 查看查询历史
```

### 2.1 query run

```bash
opennavicat query run "SELECT * FROM users WHERE status='active'" \
  --conn "Production DB" \
  --format json \
  --limit 100 \
  --show-sql
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `sql` | str | **必填** SQL 语句 |
| `--conn`, `-c` | str | '' | 连接名 (省略用已激活连接) |
| `--format`, `-f` | str | table | 输出格式: table/json/csv |
| `--limit`, `-l` | int | 0 | 限制行数 (0=不限制) |
| `--show-sql`, `-s` | bool | False | 显示执行的 SQL |

### 2.2 query file

```bash
opennavicat query file ./migrations/001_create_users.sql --conn "Production DB"
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `path` | str | **必填** .sql 文件路径 |
| `--conn`, `-c` | str | '' | 连接名 |

### 2.3 query explain

```bash
opennavicat query explain "SELECT * FROM users JOIN orders ON users.id=orders.user_id" \
  --conn "Production DB" \
  --format json
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sql` | str | **必填** | 分析 SQL |
| `--conn`, `-c` | str | '' | 连接名 |
| `--format`, `-f` | str | json | 解释格式: text/json |

### 2.4 query nl — 自然语言查询

```bash
opennavicat query nl "查询最近30天每个品类的销售额，按降序排列" \
  --conn "Production DB" \
  --format table \
  --show-sql
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `description` | str | **必填** | 自然语言描述 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--format`, `-f` | str | table | 输出格式 |
| `--show-sql` / `--hide-sql` | bool | True | 是否显示生成的 SQL |

**工作流程**:
1. 自动获取数据库 Schema 上下文（表名+列名）
2. 发送给 LLM → 生成 SQL
3. 自动执行 SQL → 返回结果

### 2.5 query history

```bash
opennavicat query history --limit 20
```

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--limit`, `-l` | int | 20 | 显示最近 N 条记录 |

---

## 3. schema — 结构管理

```bash
opennavicat schema databases    # 列出所有数据库
opennavicat schema list         # 列出数据库对象
opennavicat schema show         # 查看表结构
opennavicat schema create       # 创建表
opennavicat schema diff         # 结构比较
opennavicat schema sync         # 结构同步
opennavicat schema design       # AI 设计表结构
```

### 3.0 schema databases

```bash
opennavicat schema databases --conn "Production DB" --format json
```

列出服务器上所有数据库。

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--conn`, `-c` | str | '' | 连接名 |
| `--format`, `-f` | str | table | 输出格式 |

### 3.1 schema list

```bash
opennavicat schema list mydb --conn "Production DB" --format json
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `database` | str | **必填** 数据库名 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--format`, `-f` | str | table | 输出格式 |

### 3.2 schema show

```bash
opennavicat schema show mydb.users --conn "Production DB" --ddl
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `table` | str | **必填** | 表名 (格式: db.table) |
| `--conn`, `-c` | str | '' | 连接名 |
| `--ddl`, `-d` | bool | False | 显示 CREATE TABLE 语句 |

### 3.3 schema create

```bash
opennavicat schema create mydb.users \
  --ddl "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(255))" \
  --conn "Production DB" \
  --preview
```

```bash
opennavicat schema create mydb.orders --file ./create_orders.sql --conn "Production DB"
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | **必填** | 表名 (格式: db.table) |
| `--ddl`, `-d` | str | '' | DDL 语句文本 |
| `--file`, `-f` | str | '' | DDL 文件路径 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--preview`, `-p` | bool | False | 仅预览不执行 |

### 3.4 schema diff

```bash
opennavicat schema diff mydb mydb_staging --conn "Production DB"
```

比较两个数据库的结构差异。

| 参数 | 类型 | 说明 |
|------|------|------|
| `source` | str | **必填** 源数据库名 |
| `target` | str | **必填** 目标数据库名 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--target-conn` | str | '' | 目标连接名 (默认同源) |

### 3.5 schema sync

```bash
opennavicat schema sync mydb mydb_staging --conn "Production DB" --preview
opennavicat schema sync mydb mydb_staging --conn "Production DB" --apply
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | str | **必填** | 源数据库 |
| `target` | str | **必填** | 目标数据库 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--apply`, `-a` | bool | False | 应用变更到目标库 |
| `--preview/--no-preview` | bool | True | 应用前预览 |

### 3.6 schema design — AI 设计

```bash
opennavicat schema design "电商订单系统: 包含用户、商品、订单、支付四张表" \
  --conn "Production DB" \
  --deploy
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `description` | str | **必填** | 自然语言描述业务需求 |
| `--conn`, `-c` | str | '' | 连接名 (部署需要) |
| `--deploy`, `-d` | bool | False | 部署到数据库 |
| `--preview/--no-preview` | bool | True | 部署前预览 |

---

## 4. data — 数据操作

```bash
opennavicat data browse        # 浏览表数据
opennavicat data export        # 导出数据到文件
opennavicat data import        # 从文件导入数据
opennavicat data generate      # AI 生成测试数据
```

### 4.1 data browse

```bash
opennavicat data browse mydb.users \
  --conn "Production DB" \
  --limit 50 --offset 0 \
  --where "status='active'" \
  --order "created_at DESC" \
  --format table
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `table` | str | **必填** | 表名 (格式: db.table) |
| `--conn`, `-c` | str | '' | 连接名 |
| `--limit`, `-l` | int | 100 | 最大行数 |
| `--offset`, `-o` | int | 0 | 偏移量 |
| `--where`, `-w` | str | '' | WHERE 条件 |
| `--order` | str | '' | ORDER BY 子句 |
| `--format`, `-f` | str | table | 输出格式 |

### 4.2 data export

```bash
opennavicat data export mydb.users --output ./users.json --format json
opennavicat data export mydb.orders --output ./orders.csv --where "status='paid'"
opennavicat data export mydb.products --output ./products.xlsx --format excel
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `table` | str | **必填** | 表名 |
| `--output`, `-o` | str | auto | 输出文件路径 |
| `--format`, `-f` | str | csv | 格式: csv/json/excel |
| `--conn`, `-c` | str | '' | 连接名 |
| `--where`, `-w` | str | '' | WHERE 条件 |
| `--limit`, `-l` | int | 0 | 最大行数 |

### 4.3 data import

```bash
opennavicat data import mydb.users ./users.csv --format csv --batch-size 500
opennavicat data import mydb.users ./users.json
opennavicat data import mydb.products ./products.xlsx --format excel
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `table` | str | **必填** | 目标表 |
| `file` | str | **必填** | 输入文件 |
| `--format`, `-f` | str | auto | 文件格式: csv/json/excel/auto |
| `--conn`, `-c` | str | '' | 连接名 |
| `--batch-size`, `-b` | int | 500 | 每批插入行数 |

### 4.4 data generate — AI 测试数据

```bash
opennavicat data generate mydb.users --count 1000 \
  --prompt "中国用户真实姓名、手机号、邮箱" \
  --conn "Production DB"
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `table` | str | **必填** | 目标表 |
| `--count`, `-n` | int | 100 | 生成行数 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--prompt`, `-p` | str | '' | AI 提示词: 描述数据规则 |
| `--preview/--yes` | bool | True | 插入前预览 |

---

## 5. backup — 备份恢复

```bash
opennavicat backup create        # 备份数据库
opennavicat backup restore       # 恢复数据库
opennavicat backup list          # 列出备份文件
opennavicat backup delete        # 删除备份文件
opennavicat backup history       # 查看备份历史
opennavicat backup schedule      # 设置定时备份
opennavicat backup jobs          # 列出定时任务
opennavicat backup job-remove    # 删除定时任务
opennavicat backup job-toggle    # 启用/禁用定时任务
```

### 5.1 backup create

```bash
opennavicat backup create mydb --output ./backups/mydb_20260621.sql --compress
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `database` | str | **必填** | 数据库名 |
| `--output`, `-o` | str | auto | 输出文件 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--compress`, `-z` | bool | False | Gzip 压缩 |

### 5.2 backup restore

```bash
opennavicat backup restore mydb ./backups/mydb_20260621.sql --conn "Production DB"
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `database` | str | **必填** | 数据库名 |
| `input_file` | str | **必填** | SQL 备份文件 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--create-db` | bool | False | 自动创建数据库 |

### 5.3 backup list

```bash
opennavicat backup list --path ./backups
```

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--path`, `-p` | str | . | 备份目录 |

### 5.4 backup schedule

```bash
opennavicat backup schedule mydb --cron "0 2 * * *" --output-dir /data/backups --compress
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `database` | str | **必填** | 数据库名 |
| `--cron`, `-c` | str | "0 2 * * *" | Cron 表达式 |
| `--conn` | str | '' | 连接名 |
| `--output-dir`, `-o` | str | ./backups | 输出目录 |
| `--compress`, `-z` | bool | True | 压缩 |

### 5.5 backup delete

```bash
opennavicat backup delete ./backups/mydb_20260621.sql.gz
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `file_path` | str | **必填** 备份文件路径 |

### 5.6 backup history

```bash
opennavicat backup history --limit 20
```

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--limit`, `-n` | int | 20 | 显示最近 N 条 |

### 5.7 backup jobs

```bash
opennavicat backup jobs
```

列出所有定时备份任务。

### 5.8 backup job-remove

```bash
opennavicat backup job-remove backup_mydb_abc12345
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `job_id` | str | **必填** 任务 ID |

### 5.9 backup job-toggle

```bash
opennavicat backup job-toggle backup_mydb_abc12345 --enable
opennavicat backup job-toggle backup_mydb_abc12345 --disable
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `job_id` | str | **必填** | 任务 ID |
| `--enable/--disable` | bool | True | 启用或禁用 |

---

## 6. ai — AI 智能助手

```bash
opennavicat ai ask              # 问答
opennavicat ai optimize         # SQL 优化
opennavicat ai explain          # SQL 解释
opennavicat ai fix              # 修复 SQL
opennavicat ai chat             # 交互式对话
opennavicat ai tables           # AI 设计表结构
opennavicat ai agent            # ReAct 智能代理
opennavicat ai config           # 配置 AI 提供商
opennavicat ai test             # 测试 AI 连接
opennavicat ai chat-history     # 查看/清除聊天历史
```

### 6.1 ai ask

```bash
opennavicat ai ask "这个数据库里有哪些表？" --conn "Production DB"
opennavicat ai ask "用户的平均下单频率是多少？" --conn "Production DB"
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `question` | str | **必填** 问题 |
| `--conn`, `-c` | str | '' | 连接名 (用于 Schema 上下文) |

### 6.2 ai optimize

```bash
opennavicat ai optimize "SELECT * FROM orders WHERE YEAR(created_at)=2026" --conn "Production DB"
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sql` | str | **必填** | SQL 语句 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--explain/--no-explain` | bool | True | 包含 EXPLAIN 数据 |

### 6.3 ai explain

```bash
opennavicat ai explain "SELECT u.name, o.total FROM users u JOIN orders o ON u.id=o.user_id"
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `sql` | str | **必填** | SQL 语句 |
| `--conn`, `-c` | str | '' | 连接名 |

### 6.4 ai fix

```bash
opennavicat ai fix "SELECT * FORM users" --error "You have an error in your SQL syntax"
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sql` | str | **必填** | 有问题的 SQL |
| `--error`, `-e` | str | '' | 数据库返回的错误信息 |

### 6.5 ai chat

```bash
# 一次性提问
opennavicat ai chat --prompt "分析上个月的销售数据" --conn "Production DB" --once

# 交互式对话
opennavicat ai chat --conn "Production DB"
```

交互模式内命令:
- `!sql <query>` — 执行原始 SQL 并显示结果
- `/schema` — 显示已加载的 Schema 上下文
- `/exit` / `/quit` — 退出

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--conn`, `-c` | str | '' | 连接名 |
| `--prompt`, `-p` | str | '' | 初始提示词 |
| `--interactive/--once` | bool | True | 交互模式 |

### 6.6 ai tables

```bash
opennavicat ai tables "电商系统: 用户、商品、订单、支付、物流" --conn "Production DB" --deploy
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `description` | str | **必填** | 业务描述 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--deploy`, `-d` | bool | False | 部署到数据库 |

### 6.7 ai agent — ReAct 智能代理

```bash
opennavicat ai agent "查询所有活跃用户的最近订单" --conn "Production DB" --db mydb
```

多步推理代理：分析问题 → 搜索 Schema → 生成 SQL → 执行 → 根据结果迭代。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `request` | str | **必填** | 自然语言请求 |
| `--conn`, `-c` | str | '' | 连接名 |
| `--db`, `-d` | str | '' | 数据库名 |
| `--steps` | int | 5 | 最大推理步数 |

### 6.8 ai config

```bash
opennavicat ai config --show                              # 查看当前配置
opennavicat ai config --provider deepseek --api-key sk-xxx  # 修改配置
```

| 选项 | 类型 | 说明 |
|------|------|------|
| `--show`, `-s` | bool | 显示当前配置 |
| `--provider`, `-p` | str | 提供商: openai/deepseek/ollama/custom |
| `--api-key`, `-k` | str | API 密钥 |
| `--api-base`, `-b` | str | API 基础 URL |
| `--model`, `-m` | str | 模型名 |

### 6.9 ai test

```bash
opennavicat ai test                                    # 测试当前配置
opennavicat ai test --provider openai --api-key sk-xxx  # 测试指定配置
```

测试 AI 连接是否正常。

### 6.10 ai chat-history

```bash
opennavicat ai chat-history show                     # 查看聊天历史
opennavicat ai chat-history clear                    # 清除聊天历史
opennavicat ai chat-history show --session "prod"    # 查看指定会话
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `action` | str | show | 操作: show/clear |
| `--session`, `-s` | str | default | 会话 ID |

### 6.11 ai schema — 多轮 Schema 设计

```bash
opennavicat ai schema "users table with email and name"    # 从描述开始
opennavicat ai schema --ddl "CREATE TABLE ..."             # 从已有 DDL 开始
opennavicat ai schema "orders" --deploy --conn "MyDB"      # 设计并部署
```

交互式命令:
| 命令 | 说明 |
|------|------|
| `/show` | 显示当前 DDL |
| `/deploy` | 部署到数据库 |
| `/done` / `/exit` | 退出 |

进入交互模式后，可以连续输入修改请求，如"加个索引"、"把 status 改为 ENUM"。

### 6.12 ai build — 对话式查询构建器

```bash
opennavicat ai build "show me orders with user info"           # 开始构建查询
opennavicat ai build "monthly sales by category" --conn "MyDB" # 带 Schema 上下文
opennavicat ai build "active users" --execute                  # 构建后直接执行
```

交互式命令:
| 命令 | 说明 |
|------|------|
| `/run` | 执行当前 SQL |
| `/show` | 显示当前查询 |
| `/exit` | 退出 |

在对话中可以用自然语言逐步完善查询: "加个 status 过滤"、"按日期排序"。

---

## 7. snippet — 代码片段管理

```bash
opennavicat snippet list                    # 列出所有片段
opennavicat snippet add my_snip "SELECT *"  # 新增片段
opennavicat snippet remove 1                # 删除片段
opennavicat snippet show 1                  # 查看片段详情
```

### 7.1 snippet list

```bash
opennavicat snippet list [--format table|json|csv]
```

列出所有已保存的 SQL 代码片段。

### 7.2 snippet add

```bash
opennavicat snippet add "get_users" "SELECT * FROM users WHERE active = 1" \
  --desc "Fetch active users"
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | str | — | 片段名称 |
| `sql` | str | — | SQL 代码 |
| `--desc`, `-d` | str | '' | 描述 |
| `--force`, `-f` | bool | false | 跳过确认 |

### 7.3 snippet remove

```bash
opennavicat snippet remove 1          # 删除 ID 为 1 的片段
opennavicat snippet remove 1 --force  # 跳过确认
```

### 7.4 snippet show

```bash
opennavicat snippet show 1            # 显示片段 #1 的完整内容
```

---

## 8. 输出格式

所有支持 `--format` 的命令可以使用以下输出格式:

| 格式 | 场景 | 示例 |
|------|------|------|
| `table` | 终端阅读 | Rich 表格渲染 |
| `json` | 程序处理、jq 管道 | `opennavicat ... --format json \| jq '.data'` |
| `csv` | 电子表格导入 | `opennavicat ... --format csv > output.csv` |
| `markdown` | 文档嵌入 | `opennavicat ... --format markdown` |

---

## 9. 环境配置

```bash
# AI 提供商配置
export OPENNAVICAT_AI_PROVIDER=openai      # openai | deepseek | ollama | custom
export OPENNAVICAT_AI_API_KEY=sk-xxx       # API 密钥
export OPENNAVICAT_AI_API_BASE=https://api.openai.com/v1  # 自定义 API 地址
export OPENNAVICAT_AI_MODEL=gpt-4o-mini    # 模型名

# 强制 GUI 模式
export OPENNAVICAT_MODE=gui
```
