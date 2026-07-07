# 教程 1：AI 分析电商数据库 → 生成报表

**目标：** 连接一个 MySQL 电商数据库，用自然语言查询销售数据，AI 生成分析报表。

---

## 1. 添加数据库连接

```bash
opennavicat conn add \
  --name ecommerce \
  --host localhost \
  --port 3306 \
  --user root \
  --password mypassword \
  --database shop
```

测试连接：
```bash
opennavicat conn open ecommerce
```

## 2. AI 自然语言查询

```bash
# 查看有哪些表
opennavicat ai ask "list all tables in the database"

# 分析销售趋势
opennavicat query nl "show me monthly revenue for 2026, grouped by month"

# 找到高价值客户
opennavicat query nl "top 10 customers by total spending with their email and city"

# 识别滞销商品
opennavicat ai ask "which products have zero sales in the last 90 days"
```

## 3. AI 优化慢查询

```bash
# 假设发现一个慢查询
opennavicat ai optimize "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id WHERE YEAR(o.created_at) = 2026"
```

## 4. 使用 Agent 自动分析

```bash
opennavicat ai agent "analyze the sales data and find: 1) which product category generates most revenue 2) the average order value by month 3) customer retention rate" --db shop
```

## 5. 导出分析结果

```bash
# 将报表导出为 CSV
opennavicat data export --query "SELECT DATE_FORMAT(created_at, '%Y-%m') as month, SUM(total) as revenue FROM orders GROUP BY month ORDER BY month" --format csv > monthly_revenue.csv
```

## 6. 在 GUI 中可视化

```bash
opennavicat gui
```

在 GUI 中：
1. 左侧浏览器 → 选择 `ecommerce` 连接
2. 打开 `orders` 表查看数据
3. 点击 AI 助手按钮，输入 "show me monthly revenue as a bar chart"
4. 在 BI Dashboard 标签页中配置图表

---

## 成果

你刚刚完成了一个完整的 AI 驱动数据库分析流程：

- ✅ 自然语言 → SQL（无需手写复杂查询）
- ✅ AI 性能优化
- ✅ Agent 多步推理分析
- ✅ 数据导出 + GUI 可视化
