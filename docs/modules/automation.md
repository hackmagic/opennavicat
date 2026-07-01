# 自动化调度模块详细设计

> 模块: automation_service

## 1. 功能描述

定时执行数据库管理任务，如备份、数据传输、SQL 查询、数据同步、导入导出等。

## 2. 任务类型

| 任务 | 说明 |
|------|------|
| 备份 (Backup) | 定时 mysqldump，可选邮件发送 |
| 查询 (Query) | 定时执行 SQL，结果可导出/邮件 |
| 数据传输 (Transfer) | 定时跨库迁移数据 |
| 数据同步 (Sync) | 定时结构/数据同步 |
| 数据生成 (Generate) | 定时生成测试数据 |
| 数据字典 (Dictionary) | 定时生成并导出数据字典 PDF |
| 导入/导出 (Import/Export) | 定时文件导入或导出 |

## 3. 调度引擎

使用 APScheduler：

```python
from apscheduler.schedulers.qt import QtScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = QtScheduler()

# 每天凌晨 2 点备份
scheduler.add_job(
    backup_job,
    CronTrigger(hour=2, minute=0),
    args=[connection_id, output_dir],
    id="daily-backup",
)
```

## 4. 作业存储

SQLite 存储作业配置：

```sql
CREATE TABLE automation_jobs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    job_type     TEXT NOT NULL,  -- backup/query/transfer/sync/import/export
    connection_id TEXT NOT NULL,
    config       TEXT NOT NULL,  -- JSON: 具体任务参数
    cron_expr    TEXT NOT NULL,  -- cron 表达式
    enabled      INTEGER DEFAULT 1,
    notify_email TEXT DEFAULT '',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_run     TIMESTAMP,
    last_status  TEXT             -- success/failed
);
```
