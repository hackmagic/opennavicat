# 同步引擎模块详细设计

> 模块: sync_service / transfer_service

## 1. 功能描述

### 结构同步 (Structure Synchronization)
比较两个数据库的 Schema 差异，生成同步脚本：
- 缺失的表 → CREATE TABLE
- 多余的列/索引/外键 → DROP
- 变化的列/索引/外键 → ALTER TABLE ... MODIFY

### 数据同步 (Data Synchronization)
行级数据比较：
- 比对主键，标记新增/修改/删除的行
- 生成 INSERT / UPDATE / DELETE 语句

### 数据传输 (Data Transfer)
跨服务器（甚至跨数据库类型）的数据迁移。

## 2. 结构同步算法

```
1. 获取来源库和目标库的表列表
2. 对于每个表:
   a. 表存在性检查
   b. 列对比: 名称 → 类型/可空/默认值/注释
   c. 索引对比: 名称 → 列/唯一性/类型
   d. 外键对比: 名称 → 引用/规则
3. 生成差异报告 (新增/删除/修改)
4. UI 显示差异 (绿色=新增, 红色=删除, 黄色=修改)
5. 用户选择要应用的变更
6. 生成并执行 SQL 脚本
```

## 3. 类设计

```python
class SyncDiff:
    """对比结果"""
    added_tables: list[TableInfo]
    removed_tables: list[str]
    modified_tables: list[TableDiff]

class TableDiff:
    """单表差异"""
    table_name: str
    added_columns: list[ColumnInfo]
    removed_columns: list[str]
    modified_columns: list[(ColumnInfo, ColumnInfo)]  # (old, new)
    added_indexes: list[IndexInfo]
    removed_indexes: list[str]
    added_foreign_keys: list[ForeignKeyInfo]
    removed_foreign_keys: list[str]
```

## 4. UI 设计

```
┌──────────────────────────────────────────────────────────┐
│ Source: [mydb@localhost]  →  Target: [mydb_staging@dev] │
├──────────────────────────────────────────────────────────┤
│  Differences Found:                                       │
│                                                          │
│  ☑ New Table: `orders`              CREATE TABLE ...    │
│  ☑ New Column: `users.status`       ALTER TABLE ADD ... │
│  ☐ Drop Column: `users.old_field`   ALTER TABLE DROP ...│
│  ☑ Modify: `users.email` VARCHAR(255)→VARCHAR(512)     │
│  ☐ Drop Index: `idx_old`                                │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │  Preview DDL:                                       ││
│  │  CREATE TABLE `orders` ( ... );                     ││
│  │  ALTER TABLE `users` ADD COLUMN ...;                ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  [Execute] [Save Script] [Cancel]                       │
└──────────────────────────────────────────────────────────┘
```
