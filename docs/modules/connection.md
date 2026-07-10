# 连接管理模块详细设计

> 模块: connection_manager / connection_dialog / local_config / ssh_tunnel

## 1. 功能描述

管理所有数据库连接的生命周期：创建、编辑、测试、保存、打开、关闭。支持 SSH 隧道和 SSL 加密。支持 MySQL、PostgreSQL、SQLite、MongoDB、Redis 五种引擎。

## 2. 架构

```
┌──────────────────────────────────────────────────────────────┐
│  CLI: conn_cmd.py         GUI: ConnectionDialog             │
│  list/add/edit/remove/test/open                              │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│  ConnectionManager (services/connection_manager.py)          │
│  connect() / disconnect() / list_saved() / delete_saved()    │
└──────────┬──────────────────────────────┬────────────────────┘
           │                              │
┌──────────▼──────┐            ┌──────────▼──────┐
│  ConnectionPool  │            │  LocalConfigDB  │
│  (dal/)          │            │  (dal/)          │
│  内存缓存连接器   │            │  SQLite 持久化    │
│  open/close/get  │            │  save/list/del   │
└──────┬───────────┘            └──────────────────┘
       │
┌──────▼──────────────────────────────────────┐
│  MySQLConnector (aiomysql)                  │
│  PostgreSQLConnector (asyncpg)              │
│  MongoConnector (motor)                     │
│  RedisConnector (redis.asyncio)             │
│  SQLiteConnector (aiosqlite)                │
│  DuckDBConnector (duckdb)                   │
│  → SSH Tunnel (asyncssh)                    │
└─────────────────────────────────────────────┘
```

## 3. 类设计

### ConnectionInfo (models/connection.py)

```python
@dataclass
class ConnectionInfo:
    id: str          # UUID hex(12)
    name: str        # 用户自定义名称
    engine: str      # 数据库引擎: mysql|postgresql|sqlite|mongodb|redis
    host: str        # 数据库主机
    port: int        # 端口 (默认 3306)
    user: str        # 用户名
    password: str    # 密码 (内存明文, 存储加密)
    database: str    # 默认数据库 (可选)
    charset: str     # 字符集 (utf8mb4)
    use_ssh: bool    # SSH 隧道开关
    ssh_host/port/user/password/key_file
    use_ssl: bool    # SSL 开关
    ssl_ca/cert/key
    pool_min/max     # 连接池大小
    connect_timeout  # 超时秒数
```

### ConnectionDialog (ui/dialogs/connection_dialog.py)

三标签页对话框:
- **General**: 主机/端口/用户/密码/数据库/字符集
- **SSH**: 隧道配置（勾选后启用字段）
- **SSL**: 证书配置（勾选后启用字段）

按钮: [Test Connection] [OK] [Cancel]

### ConnectionManager (services/connection_manager.py)

```
connect(info)       → ConnectionPool.open(info)
                        └─ SSH? → SSHTunnel → MySQLConnector
                      → LocalConfigDB.save_connection(info)
disconnect(id)      → ConnectionPool.close(id)
                        └─ MySQLConnector.disconnect()
                        └─ SSHTunnel.close() (if exists)
list_saved()        → LocalConfigDB.list_connections()
get_saved(id)       → LocalConfigDB.get_connection(id)
delete_saved(id)    → ConnectionPool.close(id)
                      → LocalConfigDB.delete_connection(id)
```

### LocalConfigDB (dal/local_config.py)

SQLite 表结构:

```sql
CREATE TABLE connections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT '127.0.0.1',
    port INTEGER NOT NULL DEFAULT 3306,
    user TEXT NOT NULL DEFAULT 'root',
    password TEXT DEFAULT '',          -- AES-GCM 加密
    database TEXT DEFAULT '',
    charset TEXT DEFAULT 'utf8mb4',
    use_ssh INTEGER DEFAULT 0,
    ssh_host TEXT DEFAULT '',
    ssh_port INTEGER DEFAULT 22,
    ssh_user TEXT DEFAULT '',
    ssh_password TEXT DEFAULT '',
    ssh_key_file TEXT DEFAULT '',
    use_ssl INTEGER DEFAULT 0,
    ssl_ca TEXT DEFAULT '',
    ssl_cert TEXT DEFAULT '',
    ssl_key TEXT DEFAULT '',
    color TEXT DEFAULT '#4A90D9',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sql_text TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 4. SSH 隧道流程

```
1. SSHTunnel.connect()
   - paramiko.SSHClient()
   - 设置 AutoAddPolicy (或 StrictHostKeyChecking)
   - connect(ssh_host, ssh_port, ssh_user, password/pkey)
   - Transport.request_port_forward("", local_port, db_host, db_port)

2. MySQLConnector 连接
   - 修改 host = "127.0.0.1"
   - 修改 port = local_port
   - connect() → 通过 SSH 隧道到达目标

3. 关闭
   - 先 MySQLConnector.disconnect()
   - 再 SSHTunnel.close()
```

## 5. 密码安全

```
密码明文
    ↓
cryptography.Fernet (AES-128-GCM)
    ↓
PBKDF2HMAC (SHA-256, 100000 iterations)
    ↓
机器标识 (COMPUTERNAME)
    ↓
加密密文 → SQLite
```

- 加密在内存中完成
- 密钥不通过网络传输
- 更换机器后原有密码无法解密

## 6. CLI 命令示例

```bash
# 添加连接并测试
opennavicat conn add --name "Prod" --host prod.example.com --user admin --test

# 通过 SSH 添加
opennavicat conn add --name "Staging" --host db.internal \
  --ssh-host bastion.example.com --ssh-user jump \
  --test

# 添加 MongoDB 连接
opennavicat conn add --name "Analytics" --engine mongodb --host mongo.example.com --port 27017

# 添加 Redis 连接
opennavicat conn add --name "Cache" --engine redis --host redis.example.com --port 6379

# 激活连接
opennavicat conn open "Prod"

# 删除
opennavicat conn remove "Old Server" --force
```

## 7. 连接存储位置

| 平台 | 路径 |
|------|------|
| Windows | `%APPDATA%\OpenNavicat\data\connections.sqlite` |
| macOS | `~/Library/Application Support/OpenNavicat/data/connections.sqlite` |
| Linux | `~/.config/OpenNavicat/data/connections.sqlite` |

## 8. 未来扩展

- **连接分组**: 文件夹/颜色标签组织连接
- **连接搜索**: 按名称/主机搜索
- **连接导入/导出**: JSON 格式连接配置交换
- **连接共享**: 加密后通过 URI 共享
- **云数据库发现**: 自动扫描云平台数据库实例
