# 教程 3：定时备份 + 自动化运维

**目标：** 配置数据库定时备份、调度 SQL 查询监控，并设置 AI 异常检测。

---

## 1. 创建备份任务

```bash
# 创建一个每日凌晨 3 点的备份
opennavicat backup schedule --name daily-backup --conn prod --cron "0 3 * * *" --retain 7

# 创建一个每周完整备份
opennavicat backup schedule --name weekly-full --conn prod --cron "0 5 * * 0" --compress
```

## 2. 查看调度任务

```bash
# 列出所有任务
opennavicat backup jobs

# 查看特定任务详情
opennavicat backup jobs --name daily-backup
```

## 3. 创建 SQL 监控任务

使用 AI 生成监控查询：

```bash
opennavicat ai ask "write a SQL query to find long-running transactions and deadlocks in MySQL"
```

将得到的 SQL 配置为定时任务（通过 GUI Scheduler 面板或直接调用）：

```bash
opennavicat query run "SELECT * FROM information_schema.INNODB_TRX WHERE TIME_TO_SEC(TIMEDIFF(NOW(), trx_started)) > 60"
```

## 4. AI 异常检测

```bash
# 分析 orders 表的异常数据
opennavicat ai anomaly orders total --conn prod

# 数据质量检查
opennavicat ai data-quality users --conn prod
```

## 5. 恢复演练

```bash
# 列出可用备份
opennavicat backup list

# 恢复到测试环境
opennavicat backup restore --backup-id weekly-full-20260706 --conn prod-restore
```

## 6. 一键导出配置为脚本

在 GUI 中：
1. 设置好备份、同步、监控任务
2. 打开底部的 **CLI Commands** 面板
3. 点击 **Export Script** → 保存为 `.sh` 或 `.ps1`
4. 将脚本集成到 CI/CD pipeline

---

## 成果

- ✅ 零代码配置定时备份
- ✅ 自动化监控 + AI 异常检测
- ✅ 可导出的运维脚本
- ✅ 完全可重复的灾备流程
