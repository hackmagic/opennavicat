import { useState, useEffect } from "react";
import { listColumns, getTableDdl, type ColumnInfo } from "../api/commands";

interface Props {
  connectionId: string;
  database: string;
  table: string;
}

export default function TableStructure({ connectionId, database, table }: Props) {
  const [cols, setCols] = useState<ColumnInfo[]>([]);
  const [ddl, setDdl] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      listColumns(connectionId, database, table),
      getTableDdl(connectionId, database, table).catch(() => ""),
    ])
      .then(([c, d]) => {
        setCols(c);
        setDdl(d);
      })
      .finally(() => setLoading(false));
  }, [connectionId, database, table]);

  if (loading) return <div className="struct-loading">加载中...</div>;

  return (
    <div className="struct-panel">
      <div className="struct-section">
        <div className="struct-section-title">列信息</div>
        <table className="struct-table">
          <thead>
            <tr>
              <th>列名</th>
              <th>类型</th>
              <th>可空</th>
              <th>主键</th>
              <th>默认值</th>
              <th>额外</th>
            </tr>
          </thead>
          <tbody>
            {cols.map((c) => (
              <tr key={c.name}>
                <td className="cell-name">{c.name}</td>
                <td className="cell-type">{c.data_type}</td>
                <td>{c.nullable ? "是" : "否"}</td>
                <td>{c.is_primary_key ? <span className="col-pk">PK</span> : ""}</td>
                <td className="cell-default">{c.default_value ?? "—"}</td>
                <td className="cell-extra">{c.extra}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {ddl && (
        <div className="struct-section">
          <div className="struct-section-title">CREATE TABLE</div>
          <pre className="struct-ddl">{ddl}</pre>
        </div>
      )}
    </div>
  );
}
