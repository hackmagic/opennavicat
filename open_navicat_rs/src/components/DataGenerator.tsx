import { useState } from "react";
import { listColumns, executeQuery } from "../api/commands";

interface Props {
  connectionId: string;
  database: string;
}

export default function DataGenerator({ connectionId, database }: Props) {
  const [table, setTable] = useState("");
  const [rule, setRule] = useState("");
  const [rowCount, setRowCount] = useState(10);
  const [cols, setCols] = useState<string[]>([]);
  const [sampleData, setSampleData] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState("");

  const loadColumns = async () => {
    if (!table.trim()) return;
    try {
      const c = await listColumns(connectionId, database, table);
      setCols(c.map((x) => `${x.name} (${x.data_type})${x.nullable ? "" : " NOT NULL"}`));
    } catch (e) { setResult(String(e)); }
  };

  const generateData = async () => {
    if (!table.trim() || !cols.length) return;
    setLoading(true);
    setResult("");

    const schema = cols.join("\n");
    const messages = [{ role: "user", content: `根据以下 MySQL 表结构生成 ${rowCount} 条 JSON 测试数据。要求：${rule || "真实合理"}
表结构：
${schema}
返回严格的 JSON 数组，只包含 JSON，不要其他文字。` }];

    try {
      const resp = await fetch("https://api.deepseek.com/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${localStorage.getItem("ai_api_key") || ""}` },
        body: JSON.stringify({ model: localStorage.getItem("ai_model") || "deepseek-chat", messages, temperature: 0.7 }),
      });
      const data = await resp.json();
      const text = data.choices?.[0]?.message?.content || "";
      const jsonMatch = text.match(/\[[\s\S]*\]/);
      if (!jsonMatch) { setResult("AI 未返回有效 JSON"); setLoading(false); return; }

      const rows = JSON.parse(jsonMatch[0]);
      if (!Array.isArray(rows) || !rows.length) { setResult("AI 返回了空数据"); setLoading(false); return; }

      const colNames = Object.keys(rows[0]);
      const values = rows.map((r: Record<string, unknown>) => {
        const vals = colNames.map((cn) => {
          const v = r[cn];
          if (v === null || v === undefined) return "NULL";
          if (typeof v === "number") return String(v);
          return `'${String(v).replace(/'/g, "''")}'`;
        });
        return `(${vals.join(", ")})`;
      }).join(",\n");

      const sql = `INSERT INTO \`${table}\` (${colNames.map((c) => `\`${c}\``).join(", ")}) VALUES\n${values};`;
      setSampleData(sql);

      const r = await executeQuery(connectionId, sql);
      setResult(r.error ? `插入失败: ${r.error}` : `成功插入 ${r.rows_affected} 行`);
    } catch (e) { setResult(String(e)); }
    setLoading(false);
  };

  return (
    <div className="backup-panel">
      <div className="struct-section">
        <div className="struct-section-title">AI 测试数据生成</div>
        <div className="designer-form" style={{ flexWrap: "wrap" }}>
          <input placeholder="表名" value={table} onChange={(e) => setTable(e.target.value)} />
          <input type="number" min={1} max={100} value={rowCount} onChange={(e) => setRowCount(Number(e.target.value))} style={{ width: 60 }} />
          <button className="designer-btn" onClick={loadColumns}>加载表结构</button>
          <textarea placeholder="数据规则 (如: 10个中国用户, 邮箱唯一, 手机号格式)" value={rule} onChange={(e) => setRule(e.target.value)} style={{ width: "100%", background: "var(--bg-tertiary)", border: "1px solid var(--border)", color: "var(--text-primary)", borderRadius: 3, padding: 6, fontSize: 12, resize: "vertical" }} rows={2} />
          <button className="designer-btn primary" onClick={generateData} disabled={loading || !cols.length}>
            {loading ? "生成中..." : `生成 ${rowCount} 条数据`}
          </button>
        </div>
      </div>

      {cols.length > 0 && (
        <div className="struct-section">
          <div className="struct-section-title">表结构</div>
          <pre className="struct-ddl">{cols.join("\n")}</pre>
        </div>
      )}

      {sampleData && (
        <div className="struct-section">
          <div className="struct-section-title">生成的 SQL</div>
          <pre className="struct-ddl" style={{ maxHeight: 300, overflow: "auto" }}>{sampleData}</pre>
        </div>
      )}

      {result && <div className="struct-ddl">{result}</div>}
    </div>
  );
}
