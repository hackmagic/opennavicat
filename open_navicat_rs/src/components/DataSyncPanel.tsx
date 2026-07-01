import { useState } from "react";
import { dataSync, executeQuery, type DataSyncDiff } from "../api/commands";

interface ConnOption { id: string; name: string; }

interface Props {
  connections: ConnOption[];
}

export default function DataSyncPanel({ connections }: Props) {
  const [src, setSrc] = useState(connections[0] || { id: "", name: "" });
  const [srcTable, setSrcTable] = useState("");
  const [tgt, setTgt] = useState(connections.length > 1 ? connections[1] : connections[0] || { id: "", name: "" });
  const [tgtTable, setTgtTable] = useState("");
  const [pkCol, setPkCol] = useState("");
  const [diffs, setDiffs] = useState<DataSyncDiff[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState("");

  const doCompare = async () => {
    if (!src.id || !tgt.id || !srcTable || !tgtTable) return;
    setLoading(true);
    setResult("");
    try {
      const r = await dataSync(src.id, "mysql", srcTable, tgt.id, "mysql", tgtTable, pkCol);
      setDiffs(r);
    } catch (e) { setResult(String(e)); }
    setLoading(false);
  };

  const doExecute = async () => {
    if (!diffs) return;
    setLoading(true);
    let ok = 0, err = 0;
    for (const d of diffs) {
      const r = await executeQuery(src.id, d.sql);
      if (r.error) err++; else ok++;
    }
    setResult(`执行完成: ${ok} 成功, ${err} 失败`);
    setLoading(false);
  };

  return (
    <div className="backup-panel">
      <div className="struct-section">
        <div className="struct-section-title">数据同步</div>
        <div style={{ display: "flex", gap: 12, marginBottom: 8, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>源连接</div>
            <select className="saved-select" style={{ width: "100%" }} value={src.id} onChange={(e) => {
              const c = connections.find((x) => x.id === e.target.value);
              if (c) setSrc(c);
            }}>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <input placeholder="源表名" value={srcTable} onChange={(e) => setSrcTable(e.target.value)} style={{ width: "100%", marginTop: 4 }} />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>目标连接</div>
            <select className="saved-select" style={{ width: "100%" }} value={tgt.id} onChange={(e) => {
              const c = connections.find((x) => x.id === e.target.value);
              if (c) setTgt(c);
            }}>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <input placeholder="目标表名" value={tgtTable} onChange={(e) => setTgtTable(e.target.value)} style={{ width: "100%", marginTop: 4 }} />
          </div>
          <div style={{ width: 150 }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>主键列 (可选)</div>
            <input placeholder="主键" value={pkCol} onChange={(e) => setPkCol(e.target.value)} style={{ width: "100%" }} />
          </div>
          <div style={{ display: "flex", alignItems: "end", gap: 4 }}>
            <button className="designer-btn primary" onClick={doCompare} disabled={loading}>{loading ? "比较中..." : "比较"}</button>
            <button className="designer-btn execute" onClick={doExecute} disabled={!diffs || loading}>执行同步</button>
          </div>
        </div>
      </div>

      {result && <pre className="struct-ddl">{result}</pre>}

      {diffs && (
        <div className="struct-section">
          <div className="struct-section-title">同步语句 ({diffs.length})</div>
          <div style={{ maxHeight: 400, overflow: "auto" }}>
            <table className="struct-table">
              <thead><tr><th>类型</th><th>PK</th><th>SQL</th></tr></thead>
              <tbody>
                {diffs.map((d, i) => (
                  <tr key={i}>
                    <td><span className={`diff-badge diff-${d.dml_type === "DELETE" ? "drop" : "add"}`}>{d.dml_type}</span></td>
                    <td style={{ fontSize: 11 }}>{d.pk_value}</td>
                    <td style={{ fontSize: 11, fontFamily: "monospace" }}>{d.sql}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
