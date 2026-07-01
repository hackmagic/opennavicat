import { useState, useEffect, useCallback } from "react";
import { executeQuery } from "../api/commands";

interface Props { connectionId: string; database: string; }

const OBJECT_TYPES = ["view", "procedure", "function", "trigger"] as const;

export default function ObjectDesigner({ connectionId, database }: Props) {
  const [selectedType, setSelectedType] = useState<string>("view");
  const [objectNames, setObjectNames] = useState<string[]>([]);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [ddl, setDdl] = useState("");
  const [editedSql, setEditedSql] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const listObjects = useCallback(async () => {
    setLoading(true); setError(""); setSelectedName(null); setDdl("");
    try {
      let sql = "";
      if (selectedType === "view") {
        sql = `SELECT TABLE_NAME FROM information_schema.VIEWS WHERE TABLE_SCHEMA = '${database}' ORDER BY TABLE_NAME`;
      } else if (selectedType === "procedure") {
        sql = `SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = '${database}' AND ROUTINE_TYPE = 'PROCEDURE' ORDER BY ROUTINE_NAME`;
      } else if (selectedType === "function") {
        sql = `SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = '${database}' AND ROUTINE_TYPE = 'FUNCTION' ORDER BY ROUTINE_NAME`;
      } else if (selectedType === "trigger") {
        sql = `SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = '${database}' ORDER BY TRIGGER_NAME`;
      }
      const r = await executeQuery(connectionId, sql);
      setObjectNames(r.rows.map((row) => String(row[0])).filter(Boolean));
    } catch (e) { setError(String(e)); }
    setLoading(false);
  }, [connectionId, database, selectedType]);

  useEffect(() => { listObjects(); }, [listObjects]);

  const loadDdl = useCallback(async (name: string) => {
    setSelectedName(name); setLoading(true); setError("");
    try {
      let sql = "";
      if (selectedType === "view") sql = `SHOW CREATE VIEW \`${database}\`.\`${name}\``;
      else if (selectedType === "procedure") sql = `SHOW CREATE PROCEDURE \`${database}\`.\`${name}\``;
      else if (selectedType === "function") sql = `SHOW CREATE FUNCTION \`${database}\`.\`${name}\``;
      else if (selectedType === "trigger") sql = `SHOW CREATE TRIGGER \`${database}\`.\`${name}\``;
      const r = await executeQuery(connectionId, sql);
      const ddlVal = r.rows[0]?.[1];
      const ddlStr = ddlVal != null ? String(ddlVal) : "/* no DDL returned */";
      setDdl(ddlStr); setEditedSql(ddlStr);
    } catch (e) { setError(String(e)); setDdl(""); setEditedSql(""); }
    setLoading(false);
  }, [connectionId, database, selectedType]);

  const executeSql = async () => {
    try {
      await executeQuery(connectionId, editedSql);
      alert("执行成功");
      listObjects();
    } catch (e) { alert(String(e)); }
  };

  return (
    <div style={{ display: "flex", flex: 1, gap: 8, padding: 8, overflow: "hidden" }}>
      <div style={{ width: 200, display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {OBJECT_TYPES.map((t) => (
            <button key={t} className={`struct-btn ${selectedType === t ? "active" : ""}`}
              onClick={() => setSelectedType(t)} style={{ fontSize: 11, flex: 1 }}>
              {t === "view" ? "视图" : t === "procedure" ? "存储过程" : t === "function" ? "函数" : "触发器"}
            </button>
          ))}
        </div>
        <div style={{ flex: 1, overflowY: "auto", border: "1px solid #45475a", borderRadius: 4, padding: 4 }}>
          {objectNames.length === 0 ? <div className="struct-loading">无</div> : objectNames.map((n) => (
            <div key={n} className={`table-name ${selectedName === n ? "active" : ""}`}
              onClick={() => loadDdl(n)}
              style={{ cursor: "pointer", padding: "4px 8px", borderRadius: 4, background: selectedName === n ? "#45475a" : "transparent" }}>
              📄 {n}
            </div>
          ))}
        </div>
      </div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <span style={{ color: "#a6adc8", fontSize: 12 }}>{selectedName || "选择对象"}</span>
          {ddl && <button className="struct-btn" onClick={executeSql} style={{ fontSize: 11 }}>▶ 执行</button>}
        </div>
        {loading ? <div className="struct-loading">加载中...</div> : error ? <div className="error-msg">{error}</div> : (
          <textarea className="sql-editor" value={editedSql} onChange={(e) => setEditedSql(e.target.value)}
            style={{ flex: 1, minHeight: 200 }}
          />
        )}
      </div>
    </div>
  );
}
