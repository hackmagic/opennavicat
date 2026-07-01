import { useState, useEffect } from "react";
import { listColumns, listIndexes, listForeignKeys, executeQuery, type ColumnInfo, type IndexInfo, type ForeignKeyInfo } from "../api/commands";

interface Props {
  connectionId: string;
  database: string;
  table: string;
}

interface EditCol {
  name: string;
  newType: string;
  nullable: boolean;
  defaultVal: string;
}

interface NewIndex {
  name: string;
  columns: string;
  unique: boolean;
}

export default function TableDesigner({ connectionId, database, table }: Props) {
  const [cols, setCols] = useState<ColumnInfo[]>([]);
  const [indexes, setIndexes] = useState<IndexInfo[]>([]);
  const [foreignKeys, setForeignKeys] = useState<ForeignKeyInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [ddl, setDdl] = useState("");
  const [result, setResult] = useState("");
  const [editCol, setEditCol] = useState<EditCol | null>(null);
  const [newIdx, setNewIdx] = useState<NewIndex>({ name: "", columns: "", unique: false });

  const reload = async () => {
    const [c, i, fk] = await Promise.all([
      listColumns(connectionId, database, table),
      listIndexes(connectionId, database, table),
      listForeignKeys(connectionId, database, table),
    ]);
    setCols(c);
    setIndexes(i);
    setForeignKeys(fk);
    setLoading(false);
  };

  useEffect(() => { reload(); }, [connectionId, database, table]);

  const exec = async (sql: string) => {
    setDdl(sql);
    setResult("执行中...");
    const r = await executeQuery(connectionId, sql);
    setResult(r.error ? `错误: ${r.error}` : `成功 (${r.execution_time_ms}ms)`);
    if (!r.error) { await reload(); setEditCol(null); setNewIdx({ name: "", columns: "", unique: false }); }
  };

  const q = (s: string) => `\`${s}\``;
  const sq = (s: string) => `'${s.replace(/'/g, "''")}'`;

  const buildModify = (ec: EditCol): string => {
    const nn = ec.nullable ? "" : " NOT NULL";
    const def = ec.defaultVal ? ` DEFAULT ${sq(ec.defaultVal)}` : "";
    return `ALTER TABLE ${q(table)} MODIFY COLUMN ${q(ec.name)} ${ec.newType}${nn}${def};`;
  };

  const buildDrop = (col: string): string =>
    `ALTER TABLE ${q(table)} DROP COLUMN ${q(col)};`;

  const buildAddIndex = (ni: NewIndex): string => {
    if (!ni.name || !ni.columns) return "";
    const cols = ni.columns.split(",").map((c) => q(c.trim())).join(", ");
    const u = ni.unique ? "UNIQUE " : "";
    return `CREATE ${u}INDEX ${q(ni.name)} ON ${q(table)} (${cols});`;
  };

  const buildDropIndex = (name: string): string =>
    `DROP INDEX ${q(name)} ON ${q(table)};`;

  const doModify = () => editCol && exec(buildModify(editCol));
  const doDrop = (col: string) => exec(buildDrop(col));
  const doAddIndex = () => exec(buildAddIndex(newIdx));
  const doDropIndex = (name: string) => exec(buildDropIndex(name));

  const startEdit = (c: ColumnInfo) => setEditCol({ name: c.name, newType: c.data_type, nullable: c.nullable, defaultVal: c.default_value ?? "" });

  if (loading) return <div className="struct-loading">加载中...</div>;

  return (
    <div className="designer-panel">
      <div className="struct-section">
        <div className="struct-section-title">列管理</div>
        <table className="struct-table">
          <thead><tr><th>列名</th><th>类型</th><th>可空</th><th>主键</th><th>默认值</th><th>操作</th></tr></thead>
          <tbody>
            {cols.map((c) => (
              <tr key={c.name}>
                <td className="cell-name">{c.name}</td>
                <td className="cell-type">{c.data_type}</td>
                <td>{c.nullable ? "是" : "否"}</td>
                <td>{c.is_primary_key ? <span className="col-pk">PK</span> : ""}</td>
                <td className="cell-default">{c.default_value ?? "—"}</td>
                <td>
                  <button className="designer-btn" onClick={() => startEdit(c)}>编辑</button>
                  <button className="designer-btn danger" onClick={() => doDrop(c.name)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editCol && (
        <div className="struct-section">
          <div className="struct-section-title">编辑列: {editCol.name}</div>
          <div className="designer-form">
            <input value={editCol.newType} onChange={(e) => setEditCol({ ...editCol, newType: e.target.value })} placeholder="类型" />
            <label className="designer-checkbox"><input type="checkbox" checked={editCol.nullable} onChange={(e) => setEditCol({ ...editCol, nullable: e.target.checked })} /> 允许 NULL</label>
            <input value={editCol.defaultVal} onChange={(e) => setEditCol({ ...editCol, defaultVal: e.target.value })} placeholder="默认值" />
            <button className="designer-btn primary" onClick={doModify}>应用修改</button>
            <button className="designer-btn" onClick={() => setEditCol(null)}>取消</button>
          </div>
        </div>
      )}

      <div className="struct-section">
        <div className="struct-section-title">添加列</div>
        <AddColumnForm table={table} onExec={exec} cols={cols} />
      </div>

      <div className="struct-section">
        <div className="struct-section-title">索引管理</div>
        <table className="struct-table">
          <thead><tr><th>索引名</th><th>列</th><th>唯一</th><th>类型</th><th>操作</th></tr></thead>
          <tbody>
            {indexes.map((ix) => (
              <tr key={ix.name}>
                <td>{ix.name}</td>
                <td>{ix.columns.join(", ")}</td>
                <td>{ix.unique ? "是" : "否"}</td>
                <td>{ix.index_type}</td>
                <td><button className="designer-btn danger" onClick={() => doDropIndex(ix.name)}>删除</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="designer-form" style={{ marginTop: 8 }}>
          <input placeholder="索引名" value={newIdx.name} onChange={(e) => setNewIdx({ ...newIdx, name: e.target.value })} />
          <input placeholder="列名 (逗号分隔)" value={newIdx.columns} onChange={(e) => setNewIdx({ ...newIdx, columns: e.target.value })} />
          <label className="designer-checkbox"><input type="checkbox" checked={newIdx.unique} onChange={(e) => setNewIdx({ ...newIdx, unique: e.target.checked })} /> 唯一</label>
          <button className="designer-btn primary" onClick={doAddIndex} disabled={!newIdx.name || !newIdx.columns}>添加索引</button>
        </div>
      </div>

      {foreignKeys.length > 0 && (
        <div className="struct-section">
          <div className="struct-section-title">外键</div>
          <table className="struct-table">
            <thead><tr><th>约束名</th><th>列</th><th>引用表</th><th>引用列</th><th>删除规则</th><th>更新规则</th></tr></thead>
            <tbody>
              {foreignKeys.map((fk) => (
                <tr key={fk.name}>
                  <td>{fk.name}</td>
                  <td className="cell-name">{fk.column}</td>
                  <td className="cell-name">{fk.ref_table}</td>
                  <td>{fk.ref_column}</td>
                  <td style={{ fontSize: 11 }}>{fk.on_delete || "—"}</td>
                  <td style={{ fontSize: 11 }}>{fk.on_update || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(ddl || result) && (
        <div className="struct-section">
          <div className="struct-section-title">DDL 执行结果</div>
          <pre className="struct-ddl">{ddl}{result ? `\n${result}` : ""}</pre>
        </div>
      )}
    </div>
  );
}

function AddColumnForm({ table, onExec, cols }: {
  table: string;
  onExec: (sql: string) => Promise<void>;
  cols: ColumnInfo[];
}) {
  const [nc, setNc] = useState({ name: "", type: "VARCHAR(255)", nullable: true, defaultVal: "", after: "" });
  const doAdd = () => {
    if (!nc.name || !nc.type) return;
    const nn = nc.nullable ? "" : " NOT NULL";
    const def = nc.defaultVal ? ` DEFAULT '${nc.defaultVal.replace(/'/g, "''")}'` : "";
    const after = nc.after ? ` AFTER \`${nc.after}\`` : "";
    const sql = `ALTER TABLE \`${table}\` ADD COLUMN \`${nc.name}\` ${nc.type}${nn}${def}${after};`;
    setNc({ name: "", type: "VARCHAR(255)", nullable: true, defaultVal: "", after: "" });
    onExec(sql);
  };
  return (
    <div className="designer-form">
      <input placeholder="列名" value={nc.name} onChange={(e) => setNc({ ...nc, name: e.target.value })} />
      <input placeholder="类型" value={nc.type} onChange={(e) => setNc({ ...nc, type: e.target.value })} />
      <label className="designer-checkbox"><input type="checkbox" checked={nc.nullable} onChange={(e) => setNc({ ...nc, nullable: e.target.checked })} /> 允许 NULL</label>
      <input placeholder="默认值" value={nc.defaultVal} onChange={(e) => setNc({ ...nc, defaultVal: e.target.value })} />
      <select value={nc.after} onChange={(e) => setNc({ ...nc, after: e.target.value })}>
        <option value="">末尾</option>
        {cols.map((c) => <option key={c.name} value={c.name}>{c.name} 之后</option>)}
      </select>
      <button className="designer-btn primary" onClick={doAdd}>添加列</button>
    </div>
  );
}
