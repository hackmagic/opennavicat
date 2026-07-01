import { useState, useRef } from "react";
import { executeQuery } from "../api/commands";

interface Props {
  connectionId: string;
}

function parseCsv(text: string): { headers: string[]; rows: string[][] } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return { headers: [], rows: [] };
  const headers = lines[0].split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
  const rows = lines.slice(1).map((l) => {
    const vals: string[] = [];
    let cur = "", inQ = false;
    for (const ch of l) {
      if (ch === '"') { inQ = !inQ; continue; }
      if (ch === "," && !inQ) { vals.push(cur.trim()); cur = ""; continue; }
      cur += ch;
    }
    vals.push(cur.trim());
    return vals;
  });
  return { headers, rows };
}

function parseJson(text: string): { headers: string[]; rows: string[][] } {
  const data = JSON.parse(text);
  if (!Array.isArray(data) || !data.length) return { headers: [], rows: [] };
  const headers = Object.keys(data[0]);
  const rows = data.map((item: Record<string, unknown>) => headers.map((h) => String(item[h] ?? "")));
  return { headers, rows };
}

export default function DataImport({ connectionId }: Props) {
  const [preview, setPreview] = useState<{ headers: string[]; rows: string[][] } | null>(null);
  const [targetTable, setTargetTable] = useState("");
  const [result, setResult] = useState("");
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = reader.result as string;
      const parsed = file.name.endsWith(".json") ? parseJson(text) : parseCsv(text);
      setPreview(parsed);
      setTargetTable(file.name.replace(/\.(csv|json)$/i, ""));
    };
    reader.readAsText(file);
  };

  const doImport = async () => {
    if (!preview || !targetTable.trim()) return;
    setImporting(true);
    setResult("");

    const batchSize = 100;
    let total = 0, errors = 0;
    const colList = preview.headers.map((h) => `\`${h}\``).join(", ");

    for (let i = 0; i < preview.rows.length; i += batchSize) {
      const batch = preview.rows.slice(i, i + batchSize);
      const values = batch.map((row) => {
        const vals = row.map((v) => v === "" ? "NULL" : `'${v.replace(/'/g, "''")}'`).join(", ");
        return `(${vals})`;
      }).join(",\n");
      const sql = `INSERT INTO \`${targetTable}\` (${colList}) VALUES\n${values};`;
      const r = await executeQuery(connectionId, sql);
      if (r.error) errors++;
      else total += r.rows_affected;
    }

    setResult(`导入完成: ${total} 行成功, ${errors} 批失败`);
    setImporting(false);
  };

  return (
    <div className="backup-panel">
      <div className="struct-section">
        <div className="struct-section-title">数据导入 (CSV/JSON)</div>
        <div className="designer-form">
          <input ref={fileRef} type="file" accept=".csv,.json" onChange={handleFile} />
          <input placeholder="目标表名" value={targetTable} onChange={(e) => setTargetTable(e.target.value)} />
          <button className="designer-btn primary" onClick={doImport} disabled={!preview || importing}>
            {importing ? "导入中..." : "导入数据"}
          </button>
        </div>
      </div>

      {preview && (
        <div className="struct-section">
          <div className="struct-section-title">预览 ({preview.rows.length} 行)</div>
          <div className="result-table-wrapper" style={{ maxHeight: 400 }}>
            <table className="result-table">
              <thead><tr>{preview.headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {preview.rows.slice(0, 10).map((row, i) => (
                  <tr key={i}>{row.map((v, j) => <td key={j}>{v}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {result && <div className="struct-ddl">{result}</div>}
    </div>
  );
}
