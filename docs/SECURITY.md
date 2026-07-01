# 安全设计文档

> 版本: 0.1.0 | 更新: 2026-06-21

## 1. 安全原则

| 原则 | 说明 |
|------|------|
| **最小权限** | 使用连接数据库时建议使用最低必要权限的账号 |
| **传输加密** | 所有网络传输支持 SSH/SSL 加密 |
| **存储加密** | 敏感信息 (密码) 使用 AES-GCM 加密存储 |
| **参数化查询** | 所有用户输入通过参数化查询，杜绝 SQL 注入 |
| **密钥本地化** | 加密密钥由本地机器标识派生，不通过网络传输 |
| **无遥测** | 不上传任何用户数据、查询日志或统计信息 |

## 2. 密码存储

### 加密方案

```
用户密码
    ↓
cryptography.Fernet (AES-128-GCM)
    ↓
PBKDF2HMAC (SHA-256, 100000 iterations)
    ↓
机器标识 (COMPUTERNAME / hostname)
    ↓
加密密文 → SQLite (local_config.connections.password)
```

### 代码实现

```python
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def _get_machine_key() -> bytes:
    machine_id = os.environ.get("COMPUTERNAME", "default").encode()
    salt = b"opennavicat-salt-v1"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    return base64.urlsafe_b64encode(kdf.derive(machine_id))

_cipher = Fernet(_get_machine_key())

def encrypt_password(plaintext: str) -> str:
    return _cipher.encrypt(plaintext.encode()).decode()

def decrypt_password(ciphertext: str) -> str:
    return _cipher.decrypt(ciphertext.encode()).decode()
```

**安全边界**:
- 密钥文件存储在 `APPDATA/OpenNavicat/data/.machine_key`
- 更换机器后无法解密原机器存储的密码
- 解密仅在内存中进行，不落盘

## 3. 传输安全

### 3.1 SSH 隧道

```
┌──────────┐    SSH Encrypted     ┌──────────┐    MySQL Protocol    ┌──────────┐
│ OpenNav  │ ────────────────────→│ Bastion  │ ────────────────────→│ DB       │
│ (Client) │    Port 22           │ (Jump)   │    Port 3306         │ (Server) │
└──────────┘                      └──────────┘                      └──────────┘
     │                                  │
     │ Local Forward                    │
     │ 127.0.0.1:33060 → db:3306         │
```

实现: `dal/ssh_tunnel.py` — 使用 paramiko 的 `request_port_forward`

支持的认证方式:
- 密码认证
- RSA 私钥认证
- AutoAddPolicy (自动接受未知主机密钥)

### 3.2 SSL/TLS

MySQL 原生 SSL 连接配置:

```python
conn_info.use_ssl = True
conn_info.ssl_ca = "/path/to/ca.pem"
conn_info.ssl_cert = "/path/to/client-cert.pem"
conn_info.ssl_key = "/path/to/client-key.pem"
```

aiomysql 底层通过 PyMySQL 的 SSL Context 建立加密连接。

### 3.3 SSH + SSL 叠加

允许同时使用 SSH 隧道和 SSL 加密，实现双层传输加密。

## 4. SQL 注入防护

所有用户输入通过 **参数化查询** 传入：

```python
# ✅ 安全: 参数化
await cur.execute("SELECT * FROM users WHERE email = %s", (user_input,))

# ❌ 危险: 字符串拼接
await cur.execute(f"SELECT * FROM users WHERE email = '{user_input}'")
```

aiomysql/pymysql 原生支持 `%s` 占位符的参数化查询。

## 5. 连接安全

### 连接池管理

```python
class ConnectionPool:
    _connectors: dict[str, BaseConnector]  # connection_id → connector
    _tunnels: dict[str, SSHTunnel]         # connection_id → tunnel

    def close(self, connection_id: str):
        # 先关闭数据连接
        connector = self._connectors.pop(connection_id, None)
        # 再关闭 SSH 隧道
        tunnel = self._tunnels.pop(connection_id, None)
        tunnel.close()
```

断开顺序: 数据库连接 → SSH 隧道，确保资源完全释放。

## 6. 本地存储安全

| 存储内容 | 存储位置 | 加密 |
|----------|----------|------|
| 连接配置 | `APPDATA/OpenNavicat/data/connections.sqlite` | 密码字段加密 |
| 应用设置 | `APPDATA/OpenNavicat/settings.json` | 不加密 (不含敏感信息) |
| 查询历史 | SQLite `settings` 表 | 不加密 (用户可配置清除) |
| 加密密钥 | `APPDATA/OpenNavicat/data/.machine_key` | 文件系统权限保护 |

## 7. AI 安全

| 风险 | 防护措施 |
|------|----------|
| 敏感数据泄露给 LLM | Schema Context 仅含表名/列名/类型，不含数据 |
| SQL 注入通过 AI 生成 | 生成的 SQL 仍然经由参数化查询执行 |
| API Key 泄露 | 通过环境变量注入，不持久化到配置文件 |
| 第三方 AI 服务不可用 | 自动降级: 提供明确的错误提示，不静默失败 |

AI Service 发送给 LLM 的内容:
- ✅ 表名、列名、数据类型
- ❌ 实际数据行
- ❌ 密码/密钥
- ❌ 数据库连接信息

## 8. 审计与日志

| 日志类型 | 内容 | 安全级别 |
|----------|------|----------|
| 连接日志 | 连接时间、用户、主机 (不记录密码) | INFO |
| 查询日志 | SQL 语句 (可配置关闭) | DEBUG |
| 错误日志 | 错误信息 (可能包含 SQL) | WARNING |
| AI 日志 | 发送给 LLM 的内容摘要 | DEBUG |

所有日志默认输出到 stderr，不自动落盘。

## 9. 供应链安全

| 依赖 | 版本锁定 | 说明 |
|------|----------|------|
| poetry.lock | ✅ 推荐 | 锁定所有传递依赖版本 |
| pyproject.toml | ✅ 版本范围 | 指定主版本号，接受修复版本 |
| CI/CD 依赖扫描 | 📋 计划 | 集成 pip-audit 或 safety |

## 10. 安全清单 (Checklist)

- [ ] 密码使用 Fernet 加密存储
- [ ] 数据库连接使用 SSH/SSL 加密
- [ ] 所有用户输入使用参数化查询
- [ ] AI 请求不包含实际数据
- [ ] 日志不包含密码/密钥
- [ ] 加密密钥不通过网络传输
- [ ] 连接资源及时释放 (close on disconnect)
- [ ] CI/CD 流水线中包含依赖安全扫描
