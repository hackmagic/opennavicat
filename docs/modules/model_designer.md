# 模型设计器模块详细设计

> 模块: model_designer/

## 1. 功能描述

对标 Navicat Data Modeler，提供 ER 图可视化设计，支持正向工程（模型→数据库）和逆向工程（数据库→模型）。

## 2. 核心功能

| 功能 | 说明 |
|------|------|
| ER 图绘制 | 可视化创建实体/表、属性/列、关系/外键 |
| 正向工程 | 模型设计完成后 → 生成 DDL → 部署到数据库 |
| 逆向工程 | 从已有数据库加载 Schema → 生成 ER 图 |
| 模型转换 | 概念模型 → 逻辑模型 → 物理模型 |
| 数据字典 | 生成 PDF 文档，包含表/列/索引/外键说明 |

## 3. 数据结构

```python
class ModelEntity:
    """ER 图中的实体/表"""
    name: str
    columns: list[ModelColumn]
    color: str
    position: (x, y)  # 画布位置

class ModelColumn:
    name: str
    data_type: str
    is_primary_key: bool
    is_foreign_key: bool
    nullable: bool
    default: Any
    comment: str

class ModelRelation:
    """实体间关系"""
    from_entity: str
    from_column: str
    to_entity: str
    to_column: str
    relation_type: "1:1" | "1:N" | "M:N"
```

## 4. UI 设计

```
┌─────────────────────────────────────────────────────────┐
│  Model: [SalesDB]                                       │
├─────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────┐     │
│  │                                                │     │
│  │   ┌──────────┐            ┌──────────┐        │     │
│  │   │ Customers│━━━━━━━━━━▶│  Orders  │        │     │
│  │   │──────────│ 1:N       │──────────│        │     │
│  │   │ id (PK)  │           │ id (PK)  │        │     │
│  │   │ name     │           │ cust_id  │        │     │
│  │   │ email    │           │ total    │        │     │
│  │   │ phone    │           │ date     │        │     │
│  │   └──────────┘           └──────────┘        │     │
│  │                                    │         │     │
│  │                                    │ 1:N     │     │
│  │                                    ▼         │     │
│  │                              ┌──────────┐    │     │
│  │                              │ OrderItems│   │     │
│  │                              │──────────│    │     │
│  │                              │ id (PK)  │    │     │
│  │                              │ order_id  │    │     │
│  │                              │ product   │    │     │
│  │                              │ qty       │    │     │
│  │                              └──────────┘    │     │
│  └────────────────────────────────────────────────┘     │
├─────────────────────────────────────────────────────────┤
│  [Add Entity] [Add Relation] [Forward Engineer] [Export]│
└─────────────────────────────────────────────────────────┘
```

## 5. 实现技术

- **画布**: QGraphicsScene + QGraphicsView
- **实体渲染**: QGraphicsItem (圆角矩形 + 列列表)
- **关系渲染**: QGraphicsPathItem (贝塞尔曲线连接线)
- **拖拽**: 实体可拖动，连线自动更新
- **导出**: ReportLab 或 WeasyPrint 生成 PDF 数据字典
