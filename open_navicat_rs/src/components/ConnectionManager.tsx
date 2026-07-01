import { useState, useEffect } from "react";
import {
  connect,
  disconnect,
  listDatabases,
  listTables,
  listColumns,
  saveConnection,
  loadConnections,
  deleteConnection,
  type ConnectionInfo,
  type ColumnInfo,
  type SavedConnection,
} from "../api/commands";

interface Props {
  connections: { id: string; name: string; engine: string }[];
  setConnections: React.Dispatch<
    React.SetStateAction<{ id: string; name: string; engine: string }[]>
  >;
  onOpenQuery: (connId: string, db: string) => void;
  onOpenTable: (connId: string, db: string, table: string) => void;
  onOpenStructure: (connId: string, db: string, table: string) => void;
  onOpenDesigner: (connId: string, db: string, table: string) => void;
  onOpenBackup: (connId: string, db: string) => void;
  onOpenImport: (connId: string, db: string) => void;
  onOpenUserManager: (connId: string) => void;
  onOpenDataGen: (connId: string, db: string) => void;
  onOpenDashboard: (connId: string) => void;
  onOpenErModel: (connId: string, db: string) => void;
  onOpenObjectDesigner: (connId: string, db: string) => void;
}

export default function ConnectionManager({
  connections,
  setConnections,
  onOpenQuery,
  onOpenTable,
  onOpenStructure,
  onOpenDesigner,
  onOpenBackup,
  onOpenImport,
  onOpenUserManager,
  onOpenDataGen,
  onOpenDashboard,
  onOpenErModel,
  onOpenObjectDesigner,
}: Props) {
  const [showForm, setShowForm] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; items: { label: string; onClick: () => void; danger?: boolean }[] } | null>(null);

  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [ctxMenu]);
  const [dbs, setDbs] = useState<Record<string, string[]>>({});
  const [tables, setTables] = useState<Record<string, string[]>>({});
  const [columns, setColumns] = useState<Record<string, ColumnInfo[]>>({});
  const [savedConns, setSavedConns] = useState<SavedConnection[]>([]);

  useEffect(() => {
    loadConnections().then(setSavedConns).catch(() => {});
  }, []);

  const [form, setForm] = useState<ConnectionInfo>({
    name: "",
    host: "localhost",
    port: 3306,
    user: "root",
    password: "",
    database: "mysql",
    engine: "mysql",
    ssh: { enabled: false, host: "", port: 22, user: "", password: "" },
  });

  const handleConnect = async () => {
    try {
      const id = await connect(form);
      setConnections((prev) => [
        ...prev,
        { id, name: form.name || form.host, engine: form.engine },
      ]);
      setShowForm(false);
      loadDbs(id);
      // persist connection
      await saveConnection({
        name: form.name || form.host,
        host: form.host,
        port: form.port,
        user: form.user,
        password: form.password,
        database: form.database,
        engine: form.engine,
        ssh: form.ssh?.enabled ? form.ssh : undefined,
      });
      const updated = await loadConnections();
      setSavedConns(updated);
    } catch (e) {
      alert(e);
    }
  };

  const handleDisconnect = async (id: string) => {
    await disconnect(id);
    setConnections((prev) => prev.filter((c) => c.id !== id));
    const ndbs = { ...dbs };
    delete ndbs[id];
    setDbs(ndbs);
  };

  const loadDbs = async (id: string) => {
    try {
      const result = await listDatabases(id);
      setDbs((prev) => ({ ...prev, [id]: result.map((d) => d.name) }));
    } catch {}
  };

  const toggleDb = async (connId: string, db: string) => {
    const key = `${connId}:${db}`;
    if (expanded[key]) {
      setExpanded((prev) => ({ ...prev, [key]: false }));
      return;
    }
    setExpanded((prev) => ({ ...prev, [key]: true }));
    try {
      const result = await listTables(connId, db);
      setTables((prev) => ({
        ...prev,
        [key]: result.map((t) => t.name),
      }));
    } catch {}
  };

  const toggleTable = async (connId: string, db: string, table: string) => {
    const key = `${connId}:${db}:${table}`;
    if (expanded[key]) {
      setExpanded((prev) => ({ ...prev, [key]: false }));
      return;
    }
    setExpanded((prev) => ({ ...prev, [key]: true }));
    if (!columns[key]) {
      try {
        const result = await listColumns(connId, db, table);
        setColumns((prev) => ({ ...prev, [key]: result }));
      } catch {}
    }
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <span>连接</span>
        <button onClick={() => setShowForm(true)}>+</button>
      </div>

      {showForm && (
        <div className="conn-form">
          <input
            placeholder="名称"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <select
            value={form.engine}
            onChange={(e) =>
              setForm({
                ...form,
                engine: e.target.value,
                port: e.target.value === "postgresql" ? 5432 : 3306,
              })
            }
          >
            <option value="mysql">MySQL</option>
            <option value="postgresql">PostgreSQL</option>
          </select>
          <input
            placeholder="主机"
            value={form.host}
            onChange={(e) => setForm({ ...form, host: e.target.value })}
          />
          <input
            type="number"
            placeholder="端口"
            value={form.port}
            onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
          />
          <input
            placeholder="用户"
            value={form.user}
            onChange={(e) => setForm({ ...form, user: e.target.value })}
          />
          <input
            type="password"
            placeholder="密码"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          <input
            placeholder="数据库"
            value={form.database}
            onChange={(e) => setForm({ ...form, database: e.target.value })}
          />
          <label className="ssh-toggle">
            <input type="checkbox" checked={!!form.ssh?.enabled}
              onChange={(e) => setForm({ ...form, ssh: { ...form.ssh!, enabled: e.target.checked } })}
            />
            SSH 隧道
          </label>
          {form.ssh?.enabled && (
            <div className="ssh-fields">
              <input placeholder="SSH 主机" value={form.ssh!.host}
                onChange={(e) => setForm({ ...form, ssh: { ...form.ssh!, host: e.target.value } })} />
              <input type="number" placeholder="SSH 端口" value={form.ssh!.port}
                onChange={(e) => setForm({ ...form, ssh: { ...form.ssh!, port: Number(e.target.value) } })} />
              <input placeholder="SSH 用户" value={form.ssh!.user}
                onChange={(e) => setForm({ ...form, ssh: { ...form.ssh!, user: e.target.value } })} />
              <input type="password" placeholder="SSH 密码" value={form.ssh!.password}
                onChange={(e) => setForm({ ...form, ssh: { ...form.ssh!, password: e.target.value } })} />
            </div>
          )}
          <div className="conn-form-btns">
            <button onClick={handleConnect}>连接</button>
            <button onClick={() => setShowForm(false)}>取消</button>
          </div>
        </div>
      )}

      {ctxMenu && (
        <div className="context-menu" style={{ left: ctxMenu.x, top: ctxMenu.y }} onClick={(e) => e.stopPropagation()}>
          {ctxMenu.items.map((item, i) =>
            item.label === "-" ? <div key={i} className="context-menu-divider" />
              : <div key={i} className={`context-menu-item${item.danger ? " danger" : ""}`} onClick={() => { item.onClick(); setCtxMenu(null); }}>{item.label}</div>
          )}
        </div>
      )}
      {savedConns.length > 0 && !showForm && (
        <div className="saved-conns">
          <div className="sidebar-header">
            <span>已保存</span>
          </div>
          {savedConns.map((sc) => {
            const active = connections.some((c) => c.name === sc.name);
            return (
            <div key={sc.name} className="saved-conn-item">
              <span
                className="saved-conn-name"
                onClick={() => {
                  setForm({
                    name: sc.name,
                    host: sc.host,
                    port: sc.port,
                    user: sc.user,
                    password: sc.password,
                    database: sc.database,
                    engine: sc.engine,
                  });
                  setShowForm(true);
                }}
              >
                <span className={`dot ${active ? "active" : sc.engine}`} />
                {sc.name}
              </span>
              <button
                className="disconnect-btn"
                onClick={async () => {
                  await deleteConnection(sc.name);
                  setSavedConns((prev) => prev.filter((c) => c.name !== sc.name));
                }}
              >
                ×
              </button>
            </div>
            );
          })}
        </div>
      )}

      <div className="conn-list">
        {connections.map((conn) => (
          <div key={conn.id} className="conn-item">
            <div className="conn-name" onContextMenu={(e) => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, items: [
              { label: "新建查询", onClick: () => onOpenQuery(conn.id, "mysql") },
              { label: "备份/恢复", onClick: () => onOpenBackup(conn.id, "mysql") },
              { label: "数据导入", onClick: () => onOpenImport(conn.id, "mysql") },
              { label: "用户管理", onClick: () => onOpenUserManager(conn.id) },
              { label: "仪表盘", onClick: () => onOpenDashboard(conn.id) },
              { label: "-", onClick: () => {} },
              { label: "断开连接", onClick: () => handleDisconnect(conn.id), danger: true },
            ]}); }}>
              <span
                className={`dot ${conn.engine}`}
                onClick={() => loadDbs(conn.id)}
              />
              <span>{conn.name}</span>
              <button className="struct-btn" onClick={(e) => { e.stopPropagation(); onOpenBackup(conn.id, "mysql"); }} title="备份/恢复">💾</button>
              <button className="struct-btn" onClick={(e) => { e.stopPropagation(); onOpenImport(conn.id, "mysql"); }} title="数据导入">📥</button>
              <button className="struct-btn" onClick={(e) => { e.stopPropagation(); onOpenUserManager(conn.id); }} title="用户管理">👤</button>
              <button className="struct-btn" onClick={(e) => { e.stopPropagation(); onOpenDataGen(conn.id, "mysql"); }} title="测试数据">🧪</button>
              <button className="struct-btn" onClick={(e) => { e.stopPropagation(); onOpenDashboard(conn.id); }} title="仪表盘">📊</button>
              <button
                className="disconnect-btn"
                onClick={() => handleDisconnect(conn.id)}
              >
                ×
              </button>
            </div>
            {dbs[conn.id]?.map((db) => (
              <div key={db} className="db-item">
                <div
                  className="db-name"
                  onClick={() => toggleDb(conn.id, db)}
                  onContextMenu={(e) => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                    { label: "新建查询", onClick: () => onOpenQuery(conn.id, db) },
                    { label: "ER 模型", onClick: () => onOpenErModel(conn.id, db) },
                    { label: "对象设计", onClick: () => onOpenObjectDesigner(conn.id, db) },
                    { label: "备份/恢复", onClick: () => onOpenBackup(conn.id, db) },
                    { label: "数据导入", onClick: () => onOpenImport(conn.id, db) },
                    { label: "测试数据", onClick: () => onOpenDataGen(conn.id, db) },
                  ]}); }}
                >
                  <span>{expanded[`${conn.id}:${db}`] ? "▼" : "▶"}</span>
                  <span>{db}</span>
                    <button
                            className="query-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenQuery(conn.id, db);
                            }}
                          >
                            SQL
                          </button>
                          <button
                            className="struct-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenErModel(conn.id, db);
                            }}
                            title="ER 模型"
                          >
                            🔗
                          </button>
                          <button
                            className="struct-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenObjectDesigner(conn.id, db);
                            }}
                            title="对象设计"
                          >
                            🏗
                          </button>
                </div>
                {expanded[`${conn.id}:${db}`] &&
                  tables[`${conn.id}:${db}`]?.map((tbl) => {
                    const tkey = `${conn.id}:${db}:${tbl}`;
                    return (
                      <div key={tbl}>
                        <div className="table-item">
                          <span
                            className="expand-toggle"
                            onClick={() => toggleTable(conn.id, db, tbl)}
                          >
                            {expanded[tkey] ? "▼" : "▶"}
                          </span>
                          <span
                            className="table-name"
                            onClick={() => onOpenTable(conn.id, db, tbl)}
                            onContextMenu={(e) => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                              { label: "查看数据", onClick: () => onOpenTable(conn.id, db, tbl) },
                              { label: "查看结构", onClick: () => onOpenStructure(conn.id, db, tbl) },
                              { label: "设计表", onClick: () => onOpenDesigner(conn.id, db, tbl) },
                            ]}); }}
                          >
                            📋 {tbl}
                          </span>
                          <button
                            className="struct-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenStructure(conn.id, db, tbl);
                            }}
                            title="查看结构"
                          >
                            S
                          </button>
                          <button
                            className="struct-btn designer"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenDesigner(conn.id, db, tbl);
                            }}
                            title="设计表"
                          >
                            D
                          </button>
                        </div>
                        {expanded[tkey] && columns[tkey] && (
                          <div className="column-list">
                            {columns[tkey].map((col) => (
                              <div key={col.name} className="column-item">
                                <span className="col-name">{col.name}</span>
                                <span className="col-type">{col.data_type}</span>
                                {col.is_primary_key && (
                                  <span className="col-pk">PK</span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
