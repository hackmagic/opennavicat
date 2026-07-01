import { useState } from "react";
import { schemaDiff, type SchemaDiffItem } from "../api/commands";

interface ConnOption {
  id: string;
  name: string;
  database: string;
}

interface Props {
  connections: { id: string; name: string; database: string }[];
}

export default function SchemaDiff({ connections }: Props) {
  const [src, setSrc] = useState<ConnOption>(connections[0] || { id: "", name: "", database: "" });
  const [tgt, setTgt] = useState<ConnOption>(connections.length > 1 ? connections[1] : connections[0] || { id: "", name: "", database: "" });
  const [diffs, setDiffs] = useState<SchemaDiffItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const doCompare = async () => {
    if (!src.id || !tgt.id) return;
    setLoading(true);
    setErr("");
    try {
      const result = await schemaDiff(src.id, src.database, tgt.id, tgt.database);
      setDiffs(result);
    } catch (e) {
      setErr(String(e));
    }
    setLoading(false);
  };

  return (
    <div className="backup-panel">
      <div className="struct-section">
        <div className="struct-section-title">Schema 差异比较</div>
        <div style={{ display: "flex", gap: 12, alignItems: "end" }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>源库</div>
            <select className="saved-select" style={{ width: "100%" }} value={src.id} onChange={(e) => {
              const c = connections.find((x) => x.id === e.target.value);
              if (c) setSrc(c);
            }}>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.database})</option>)}
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>目标库</div>
            <select className="saved-select" style={{ width: "100%" }} value={tgt.id} onChange={(e) => {
              const c = connections.find((x) => x.id === e.target.value);
              if (c) setTgt(c);
            }}>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.database})</option>)}
            </select>
          </div>
          <button className="designer-btn primary" onClick={doCompare} disabled={loading}>
            {loading ? "比较中..." : "比较"}
          </button>
        </div>
      </div>

      {err && <div className="error-msg">{err}</div>}

      {diffs && (
        <div className="struct-section">
          <div className="struct-section-title">差异结果 ({diffs.length})</div>
          {diffs.length === 0 ? (
            <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 8 }}>两个库结构一致</div>
          ) : (
            <table className="struct-table">
              <thead><tr><th>表</th><th>差异类型</th><th>详情</th></tr></thead>
              <tbody>
                {diffs.map((d, i) => (
                  <tr key={i}>
                    <td className="cell-name">{d.table_name}</td>
                    <td><span className={`diff-badge diff-${d.diff_type.includes("ADD") ? "add" : "drop"}`}>{d.diff_type}</span></td>
                    <td style={{ fontSize: 12 }}>{d.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
