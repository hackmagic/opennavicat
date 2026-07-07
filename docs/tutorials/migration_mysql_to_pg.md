# 教程 2：数据库迁移 MySQL → PostgreSQL

**目标：** 将 MySQL 数据库结构+数据迁移到 PostgreSQL。

---

## 1. 添加两个连接

```bash
# MySQL 源库
opennavicat conn add --name mysql-source --host 192.168.1.100 --port 3306 --user root --password pass --database myapp

# PostgreSQL 目标库
opennavicat conn add --name pg-target --host 192.168.1.101 --port 5432 --user postgres --password pass --database myapp
```

## 2. 结构同步

```bash
# 查看差异
opennavicat schema diff mysql-source pg-target

# 同步结构
opennavicat schema sync mysql-source pg-target --apply
```

## 3. 数据同步

```bash
# 全量数据同步
opennavicat data sync mysql-source pg-target --apply
```

## 4. AI 辅助方言转换

如果遇到不兼容的 SQL：

```bash
# 让 AI 帮忙转换
opennavicat ai ask "convert this MySQL SQL to PostgreSQL: SELECT * FROM users WHERE DATE(created_at) = '2026-01-01'"
```

## 5. 验证迁移结果

```bash
# 切换到 PostgreSQL 查询
opennavicat conn open pg-target

# 检查行数
opennavicat query run "SELECT COUNT(*) FROM users"

# 用 AI 验证数据完整性
opennavicat ai ask "compare row counts between mysql-source and pg-target databases"
```

---

## 成果

- ✅ 无需手动编写 DDL 转换脚本
- ✅ 结构 + 数据一步完成
- ✅ AI 辅助解决方言差异
