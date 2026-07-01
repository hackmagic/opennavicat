# 对象设计器模块详细设计

> 模块: object_designer/

## 1. 功能描述

可视化创建和修改数据库对象（表、视图、存储过程、函数、事件、触发器），生成对应的 DDL 语句。

## 2. 表设计器 (TableDesigner)

### 功能列表

| 功能 | 说明 |
|------|------|
| 列管理 | 添加/删除/排序 列，编辑名称/类型/长度/默认值/注释 |
| 索引管理 | 主键/唯一/普通/全文/空间索引 |
| 外键管理 | 引用表/列、ON DELETE/UPDATE 规则 |
| 表选项 | 引擎/字符集/排序规则/AUTO_INCREMENT/注释 |
| DDL 预览 | 实时生成 CREATE/ALTER TABLE 语句 |
| 执行 | 将 DDL 发送到服务器执行 |

### SQL 生成

使用 `utils/sql_generator.py`:

- **新建表**: `generate_create_table(TableInfo)` → `CREATE TABLE ...`
- **修改表**: 对比新旧 TableInfo → `ALTER TABLE ... ADD/DROP/MODIFY`
- **删除表**: `DROP TABLE IF EXISTS ...`

### 界面布局

```
┌──────────────────────────────────────────────────────┐
│  Table: [users]  Database: [mydb]                    │
├───────┬──────────────────────────────────────────────┤
│       │  Columns                                     │
│ Table │  ┌───┬──────────┬───────┬─────┬───────────┐  │
│ ───── │  │ # │ Name     │ Type  │ Len │ Default   │  │
│ Table │  ├───┼──────────┼───────┼─────┼───────────┤  │
│       │  │ 1 │ id       │ INT   │ 11  │           │  │
│       │  │ 2 │ name     │ VARCHAR│ 255 │           │  │
│       │  │ 3 │ email    │ VARCHAR│ 255 │           │  │
│       │  └───┴──────────┴───────┴─────┴───────────┘  │
│       │                                               │
│       │  Indexes / Foreign Keys / Options              │
│       │  [tabs]                                       │
│       │                                               │
│       │  ┌──────────────────────────────────────────┐  │
│       │  │ DDL Preview                              │  │
│       │  │ CREATE TABLE `users` (                   │  │
│       │  │   `id` INT(11) NOT NULL AUTO_INCREMENT,   │  │
│       │  │   ...                                     │  │
│       │  └──────────────────────────────────────────┘  │
│       │  [Save] [Cancel]                              │
└───────┴──────────────────────────────────────────────┘
```

## 3. 视图设计器 (ViewDesigner)

- 可视化选择表/列
- 设置 JOIN 条件
- WHERE/ORDER BY/GROUP BY/HAVING 条件编辑
- 实时 SQL 预览

## 4. 存储过程/函数设计器 (RoutineDesigner)

- 代码编辑器 (语法高亮)
- 参数管理 (IN/OUT/INOUT)
- DDL 预览与执行
- 调试功能 (未来)

## 5. 未来扩展

- **事件设计器**: 定时 SQL 执行配置
- **触发器设计器**: BEFORE/AFTER INSERT/UPDATE/DELETE
- **用户管理**: GRANT/REVOKE 可视化
