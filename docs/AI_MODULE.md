# AI 模块详细设计

> 模块: services/ai_service.py | CLI: ai_cmd.py

## 1. 设计目标

让 LLM (Large Language Model) 成为数据库交互的一等公民。用户可以用自然语言完成查询、优化、设计等所有操作。

### 核心能力

```
自然语言 → SQL  ← 最核心功能
SQL → 优化建议  ← 性能调优
SQL → 自然语言解释 ← 学习/审查
错误 SQL → 修复  ← 调试辅助
业务描述 → DDL  ← 架构设计
表结构 → 测试数据 ← 开发测试
多轮对话 ← 交互式分析
```

## 2. 架构

```
┌──────────────────────────────────────────────────────────────┐
│                    AIService                                  │
├──────────────────────────────────────────────────────────────┤
│  Providers (策略模式)                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ OpenAI   │ │ DeepSeek │ │  Ollama  │ │ Custom   │       │
│  │ GPT-4o   │ │ DeepSeek │ │  Llama3  │ │ 任意 API │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
├──────────────────────────────────────────────────────────────┤
│  Features                                                    │
│  nl2sql() → optimize() → explain_query() → fix_sql()        │
│  → design_schema() → generate_data() → ask() → chat()       │
├──────────────────────────────────────────────────────────────┤
│  Context Pipeline                                             │
│  Schema Context (表/列名) → System Prompt → Chat History     │
└──────────────────────────────────────────────────────────────┘
```

## 3. 函数详解

### 3.1 nl2sql(description, schema_context) → str

**将自然语言转换为 SQL 查询**。

```
输入: "过去30天每个品类的销售额，按降序排列"
输入: schema_context (表/列信息)
      ↓
System Prompt: "You are a SQL expert. Generate clean, correct SQL queries."
User Prompt: "Database schema context:\n{schema_context}\n\nConvert this
             natural language request to a SQL query. Return ONLY the
             SQL query, no explanations:\n\n{description}"
      ↓
输出: "SELECT c.name AS category, SUM(o.total) AS revenue
       FROM orders o JOIN products p ON o.product_id = p.id
       JOIN categories c ON p.category_id = c.id
       WHERE o.created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
       GROUP BY c.id ORDER BY revenue DESC"
```

**Prompt 设计要点**:
- 包含 Schema 上下文让 LLM 知道表名和列名
- 要求"只返回 SQL，不要解释" — 方便直接执行
- Temperature: 0.1 (低随机性，精确优先)

### 3.2 optimize(sql, explain_data) → str

**分析 SQL 并给出优化建议**。

```
输入: "SELECT * FROM orders WHERE YEAR(created_at)=2026"
输入: (可选) EXPLAIN FORMAT=JSON 的结果
      ↓
System Prompt: "You are a SQL performance expert."
User Prompt: "Analyze this SQL query and suggest optimizations:
              {sql}\n\n{explain_data}\n\nProvide: 1) Performance issues
              found 2) Specific recommendations 3) Rewritten query"
      ↓
输出: "## 性能问题\n1. 使用了 YEAR() 函数包裹 created_at 列，导致无法使用索引
       2. 使用 SELECT * 查询所有列\n\n## 优化建议\n...
       ## 改写\nSELECT id, user_id, total FROM orders WHERE
       created_at >= '2026-01-01' AND created_at < '2027-01-01'"
```

### 3.3 explain_query(sql) → str

**用自然语言解释 SQL 做了什么**。

```
输入: "SELECT u.name, COUNT(o.id) AS order_count
       FROM users u LEFT JOIN orders o ON u.id = o.user_id
       GROUP BY u.id HAVING order_count > 5"
      ↓
输出: "这条查询做了以下事情: 1) 从 users 表取所有用户 ..."
```

### 3.4 fix_sql(sql, error) → str

**修复有语法错误的 SQL**。

```
输入: "SELECT * FORM users"
输入: "You have an error in your SQL syntax..."
      ↓
输出: "SELECT * FROM users"
```

### 3.5 design_schema(description) → str

**根据业务描述生成完整的 CREATE TABLE DDL**。

```
输入: "电商系统: 用户表(用户名,邮箱,手机号), 商品表(名称,价格,库存),
       订单表(用户,商品,数量,总价,状态,时间)"
      ↓
Prompt: "- Use InnoDB engine\n- Include appropriate data types, constraints
         - Primary keys, foreign keys, useful indexes\n- utf8mb4 charset
         - Return ONLY the DDL, no explanations"
      ↓
输出: "CREATE TABLE users (...); CREATE TABLE products (...);
       CREATE TABLE orders (...);"
```

**关键设计**: 输出直接是 DDL，不需要后处理即可执行或预览。

### 3.6 generate_data(table_info, count, prompt) → list[dict]

**生成符合 Schema 和业务规则的测试数据**。

```
输入: TableInfo (列名+类型) + count=1000 + prompt="中国用户真实信息"
      ↓
Prompt: "Generate 1000 realistic JSON records for this MySQL table schema:
         {schema}\n\nBusiness rules: {prompt}\n\nReturn ONLY a JSON array"
      ↓
输出: [{"name": "张三", "email": "zhangsan@test.com", "phone": "13800138000"}, ...]
```

**关键设计**: Temperature: 0.8 (高随机性，数据多样) + JSON 解析容错

### 3.7 ask(question, schema_context) → str

**通用数据库问答** — 任何关于数据库的问题都可以问。

### 3.8 chat(message) → str

**多轮对话** — 维护聊天历史，支持连续追问。

```
# 历史管理: 保留最近 20 轮对话，超过 40 条时截断
self._chat_history: list[{"role": "user"|"assistant", "content": str}]
```

## 4. Prompt 工程策略

### 4.1 系统提示词

每个功能使用定制化 System Prompt:

| 功能 | System Prompt |
|------|--------------|
| nl2sql | "You are a SQL expert. Generate clean, correct SQL queries." |
| optimize | "You are a SQL performance expert." |
| explain_query | "You are a SQL teacher explaining concepts clearly." |
| fix_sql | "You are a SQL debugging expert. Fix queries efficiently." |
| design_schema | "You are a database architect. Design clean, normalized schemas." |
| generate_data | "You are a data generator. Return ONLY valid JSON arrays." |

### 4.2 Schema Context 构建

```python
def _get_schema_context(conn_id: str) -> str:
    dbs = metadata_service.list_databases(conn_id)
    for db in dbs[:5]:                    # 最多 5 个数据库
        tables = list_tables(conn_id, db)
        for table in tables[:20]:         # 每库最多 20 张表
            info = get_table_info(conn_id, db, table)
            cols = ", ".join(f"{c.name} ({c.data_type})" for c in info.columns[:10])
            lines.append(f"{db}.{table}: {cols}")
    return "\n".join(lines)
```

限制策略: 防止 Token 溢出，只加载库/表/列名，不加载索引和数据。

### 4.3 错误处理容错

```python
def generate_data(...) -> list[dict]:
    response = self._call_llm(messages, temperature=0.8)
    try:
        # 从响应中提取 JSON 数组（LLM 可能添加额外文字）
        start = response.find("[")
        end = response.rfind("]") + 1
        json_str = response[start:end]
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return []  # 优雅降级
```

## 5. 提供商配置

| 变量 | 说明 | 示例 |
|------|------|------|
| `OPENNAVICAT_AI_PROVIDER` | 提供商 | `openai` / `deepseek` / `ollama` / `custom` |
| `OPENNAVICAT_AI_API_KEY` | API 密钥 | `sk-xxx` |
| `OPENNAVICAT_AI_API_BASE` | 自定义 API 地址 | `http://localhost:11434` (Ollama) |
| `OPENNAVICAT_AI_MODEL` | 模型名 | `gpt-4o-mini` / `deepseek-chat` / `llama3` |

### 快速配置示例

```bash
# OpenAI
export OPENNAVICAT_AI_PROVIDER=openai
export OPENNAVICAT_AI_API_KEY=sk-xxxxx
export OPENNAVICAT_AI_MODEL=gpt-4o-mini

# DeepSeek (免费额度)
export OPENNAVICAT_AI_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-xxxxx

# 本地 Ollama
export OPENNAVICAT_AI_PROVIDER=ollama
export OPENNAVICAT_AI_API_BASE=http://localhost:11434
export OPENNAVICAT_AI_MODEL=llama3
```

## 6. 未来扩展

| 功能 | 说明 |
|------|------|
| **RAG 增强** | 将表结构预编码为向量嵌入，提升 NL→SQL 准确性 |
| **Function Calling** | LLM 直接调用数据库操作函数，而非先生成 SQL |
| **多轮 Schema 设计** | "加个索引" "这张表要分区" 等连续设计对话 |
| **数据质量分析** | "检查 email 列的格式是否正确" |
| **异常检测** | "检测 orders 表中是否存在异常数据" |
| **AI Agent (ReAct)** | LLM 自主规划多步操作: 查 Schema → 写 SQL → 执行 → 分析结果 |
