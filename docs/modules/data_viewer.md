# 数据查看器模块详细设计

> 模块: table_viewer / data_cmd

## 1. 功能描述

以网格 (Grid View) 形式展示表数据，支持分页、排序、筛选、导出。CLI 模式是主要交互方式，GUI 模式提供可视化编辑。

## 2. CLI 模式 (data 命令组)

### 子命令

| 命令 | 说明 | 用法 |
|------|------|------|
| `data browse` | 浏览表数据 | `data browse db.table --limit 100 --where "status='active'"` |
| `data export` | 导出到文件 | `data export db.table --format json --output data.json` |
| `data import` | 从文件导入 | `data import db.table data.csv --batch-size 500` |
| `data generate` | AI 生成测试数据 | `data generate db.table --count 1000` |
| `data profile` | 列统计分析 | `data profile db.table --sample 5000` |

### 2.1 data browse

```
opennavicat data browse mydb.users \
  --limit 50 --offset 100 \
  --where "status='active'" \
  --order "created_at DESC" \
  --format table
```

参数:
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `table` | str | 必填 | 格式: db.table |
| `--limit` | int | 100 | 最大行数 |
| `--offset` | int | 0 | 偏移量 |
| `--where` | str | '' | WHERE 条件 |
| `--order` | str | '' | ORDER BY |
| `--format` | str | table | 输出格式 |

### 2.2 data export

支持格式: csv / json / excel

### 2.3 data import

支持格式: csv / json / excel，自动检测或手动指定。

### 2.4 data generate

AI 驱动: 传入表结构和业务规则 → LLM 生成 JSON → 批量插入。

## 3. GUI 模式 (TableViewerWidget)

### 3.1 界面布局

```
┌──────────────────────────────────────────────────────────┐
│ [↻Refresh] [+Add Row] [−Delete] | Filter: [___] [Apply] │ Rows/page: [500]
├──────────────────────────────────────────────────────────┤
│  id │ name    │ email             │ created_at           │
│─────│─────────│───────────────────│──────────────────────│
│  1  │ Alice   │ alice@test.com    │ 2026-01-15 10:30:00  │
│  2  │ Bob     │ bob@test.com      │ 2026-01-16 14:20:00  │
│  3  │ Charlie │ charlie@test.com  │ 2026-01-17 09:15:00  │
│ ... │         │                   │                      │
├──────────────────────────────────────────────────────────┤
│ [⏮ First] [◀ Prev]  Page 1 of 10  [Next ▶] [Last ⏭]    │ Total rows: 5000 │
└──────────────────────────────────────────────────────────┘
```

### 3.2 分页实现

```sql
-- 总行数
SELECT COUNT(*) FROM `db`.`table` [WHERE ...]
-- 分页查询
SELECT * FROM `db`.`table` [WHERE ...] [ORDER BY ...] LIMIT {page_size} OFFSET {offset}
```

### 3.3 筛选

用户输入 WHERE 子句片段 → 构建完整 SQL → 重新查询。

### 3.4 内联编辑 (GUI 模式)

```
用户编辑单元格
  → 提取主键 (或整行作为条件)
  → 生成 UPDATE `table` SET `col`=%s WHERE `pk`=%s
  → 执行并刷新当前行
```

## 4. 数据导出实现

```python
def export_data(conn_id, table, output, format, where, limit):
    # 1. 查询数据
    result = query_engine.execute(conn_id, f"SELECT * FROM {table}...")
    
    # 2. 转换格式
    data = [{c.name: v for c, v in zip(result.columns, row)} for row in result.rows]
    
    # 3. 写入文件
    if format == "json":
        json.dump(data, f, ensure_ascii=False, default=str)
    elif format == "csv":
        csv.DictWriter(f, fieldnames=result.columns).writerows(data)
    elif format == "excel":
        wb = openpyxl.Workbook()
        ws.append(result.columns) + data
        wb.save(output)
```

## 5. 数据导入实现

```python
def import_data(conn_id, table, file, format, batch_size=500):
    # 1. 加载文件
    data = load_file(file, format)  # → list[dict]
    
    # 2. 分批插入
    for batch in chunks(data, batch_size):
        connector = connection_pool.get(conn_id)
        inserted = asyncio.run(
            connector.batch_insert(database, table_name, batch)
        )
```

## 6. 未来扩展

- **表单视图 (Form View)**: 单条记录纵向展示
- **BLOB 查看器**: 图片/文本/Hex 多模式预览
- **外键选择器**: 双击 FK 字段 → 弹出关联数据选择
- **数据剖析 (Data Profiling)**: 列统计/分布图/完整性分析
- **条件格式化**: 单元格颜色/图标/数据条
- **增量同步**: 基于时间戳/版本号的数据同步
