import { useState, useCallback } from "react";
import ConnectionManager from "./components/ConnectionManager";
import QueryEditor from "./components/QueryEditor";
import TableStructure from "./components/TableStructure";
import TableDesigner from "./components/TableDesigner";
import BackupRestore from "./components/BackupRestore";
import DataImport from "./components/DataImport";
import SchemaDiff from "./components/SchemaDiff";
import UserManager from "./components/UserManager";
import DataGenerator from "./components/DataGenerator";
import DataSyncPanel from "./components/DataSyncPanel";
import SettingsDialog from "./components/SettingsDialog";
import Dashboard from "./components/Dashboard";
import ErModel from "./components/ErModel";
import ObjectDesigner from "./components/ObjectDesigner";
import Scheduler from "./components/Scheduler";
import AiPanel from "./components/AiPanel";
import { I18nCtx, t, type Lang } from "./i18n";
import "./App.css";

export interface Tab {
  id: string;
  title: string;
  connectionId: string;
  database: string;
  initialSql?: string;
  table?: string;
          kind?: "query" | "structure" | "designer" | "backup" | "import" | "schema" | "users" | "data-gen" | "data-sync" | "dashboard" | "ermodel" | "object" | "scheduler";
}

function App() {
  const [lang, setLang] = useState<Lang>(() => {
    try { return (JSON.parse(localStorage.getItem("opennavicat_settings") || "{}").language) || "zh"; } catch { return "zh"; }
  });
  // init theme
  useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem("opennavicat_settings") || "{}");
      if (s.theme === "latte") document.documentElement.className = "theme-latte";
    } catch {}
  });

  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [connections, setConnections] = useState<
    { id: string; name: string; engine: string }[]
  >([]);
  const [showAi, setShowAi] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const onSqlGenerated = useCallback((sql: string) => {
    const conn = connections[0];
    if (!conn) return;
    const tab: Tab = {
      id: crypto.randomUUID(),
      title: "AI 查询",
      connectionId: conn.id,
      database: "mysql",
      initialSql: sql,
      table: undefined,
    };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  }, [connections]);

  const openTab = (connId: string, db: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"}.${db}`;
    const existing = tabs.find((t) => t.title === title && !t.initialSql);
    if (existing) {
      setActiveTab(existing.id);
      return;
    }
    const tab: Tab = {
      id: crypto.randomUUID(),
      title,
      connectionId: connId,
      database: db,
    };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openTable = (connId: string, db: string, table: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"}.${db}.${table}`;
    const existing = tabs.find((t) => t.title === title && t.kind === "query");
    if (existing) {
      setActiveTab(existing.id);
      return;
    }
    const tab: Tab = {
      id: crypto.randomUUID(),
      title,
      connectionId: connId,
      database: db,
      table,
      initialSql: `SELECT * FROM \`${table}\` LIMIT 100`,
      kind: "query",
    };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openStructure = (connId: string, db: string, table: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"}.${db}.${table} 结构`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) {
      setActiveTab(existing.id);
      return;
    }
    const tab: Tab = {
      id: crypto.randomUUID(),
      title,
      connectionId: connId,
      database: db,
      table,
      kind: "structure",
    };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openDesigner = (connId: string, db: string, table: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"}.${db}.${table} 设计`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = {
      id: crypto.randomUUID(), title, connectionId: connId, database: db,
      table, kind: "designer",
    };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openBackup = (connId: string, db: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"} 备份恢复`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: connId, database: db, kind: "backup" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openImport = (connId: string, db: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"} 数据导入`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: connId, database: db, kind: "import" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openSchemaDiff = () => {
    const title = "Schema 差异比较";
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: "", database: "", kind: "schema" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openUserManager = (connId: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"} 用户管理`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: connId, database: "", kind: "users" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openDataGen = (connId: string, db: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"} 测试数据`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: connId, database: db, kind: "data-gen" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openDataSync = () => {
    const title = "数据同步";
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: "", database: "", kind: "data-sync" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openScheduler = () => {
    const title = "备份调度";
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: "", database: "", kind: "scheduler" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openObjectDesigner = (connId: string, db: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"}.${db} 对象设计`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: connId, database: db, kind: "object" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openErModel = (connId: string, db: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"}.${db} ER 模型`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: connId, database: db, kind: "ermodel" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const openDashboard = (connId: string) => {
    const conn = connections.find((c) => c.id === connId);
    const title = `${conn?.name || "?"} 仪表盘`;
    const existing = tabs.find((t) => t.title === title);
    if (existing) { setActiveTab(existing.id); return; }
    const tab: Tab = { id: crypto.randomUUID(), title, connectionId: connId, database: "", kind: "dashboard" };
    setTabs((prev) => [...prev, tab]);
    setActiveTab(tab.id);
  };

  const closeTab = (id: string) => {
    setTabs((prev) => prev.filter((t) => t.id !== id));
    if (activeTab === id) {
      const idx = tabs.findIndex((t) => t.id === id);
      const next = tabs[idx - 1] || tabs[idx + 1];
      setActiveTab(next?.id || null);
    }
  };

  return (
    <I18nCtx.Provider value={lang}>
    <div className="app">
        <ConnectionManager
          connections={connections}
          setConnections={setConnections}
          onOpenQuery={openTab}
          onOpenTable={openTable}
          onOpenStructure={openStructure}
          onOpenDesigner={openDesigner}
          onOpenBackup={openBackup}
          onOpenImport={openImport}
          onOpenUserManager={openUserManager}
          onOpenDataGen={openDataGen}
          onOpenDashboard={openDashboard}
          onOpenErModel={openErModel}
          onOpenObjectDesigner={openObjectDesigner}
        />
      <div className="main-area">
        <div className="main-toolbar">
          <button className="toolbar-btn" onClick={openSchemaDiff}>{t(lang, "toolbar.struct_diff")}</button>
          <button className="toolbar-btn" onClick={openDataSync}>{t(lang, "toolbar.data_sync")}</button>
          <button className="toolbar-btn" onClick={openScheduler}>{t(lang, "toolbar.backup_schedule")}</button>
          <button className="toolbar-btn" onClick={() => setShowSettings(true)}>{t(lang, "toolbar.settings")}</button>
          <button className="ai-toggle-btn" onClick={() => setShowAi((s) => !s)}>
            {showAi ? "✕ AI" : "🤖 AI"}
          </button>
        </div>
        <div className="main-content">
          {tabs.length === 0 ? (
            <div className="welcome">
              <h1>{t(lang, "app.title")}</h1>
              <p>{t(lang, "app.welcome")}</p>
            </div>
          ) : (
            <>
              <div className="tab-bar">
                {tabs.map((tab) => (
                  <div
                    key={tab.id}
                    className={`tab ${activeTab === tab.id ? "active" : ""}`}
                    onClick={() => setActiveTab(tab.id)}
                  >
                    <span>{tab.title}</span>
                    <button
                      className="tab-close"
                      onClick={(e) => {
                        e.stopPropagation();
                        closeTab(tab.id);
                      }}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
              {tabs.map((tab) => {
                if (activeTab !== tab.id) return null;
              if (tab.kind === "structure") {
                return (
                  <TableStructure
                    key={tab.id}
                    connectionId={tab.connectionId}
                    database={tab.database}
                    table={tab.table!}
                  />
                );
              }
              if (tab.kind === "designer") {
                return (
                  <TableDesigner
                    key={tab.id}
                    connectionId={tab.connectionId}
                    database={tab.database}
                    table={tab.table!}
                  />
                );
              }
              if (tab.kind === "backup") {
                return (
                  <BackupRestore
                    key={tab.id}
                    connectionId={tab.connectionId}
                    database={tab.database}
                  />
                );
              }
              if (tab.kind === "import") {
                return (
                  <DataImport
                    key={tab.id}
                    connectionId={tab.connectionId}
                  />
                );
              }
              if (tab.kind === "schema") {
                return (
                  <SchemaDiff
                    key={tab.id}
                    connections={connections.map((c) => ({ id: c.id, name: c.name, database: "mysql" }))}
                  />
                );
              }
              if (tab.kind === "users") {
                return <UserManager key={tab.id} connectionId={tab.connectionId} />;
              }
              if (tab.kind === "data-gen") {
                return <DataGenerator key={tab.id} connectionId={tab.connectionId} database={tab.database} />;
              }
              if (tab.kind === "data-sync") {
                return <DataSyncPanel key={tab.id} connections={connections.map((c) => ({ id: c.id, name: c.name }))} />;
              }
              if (tab.kind === "dashboard") {
                return <Dashboard key={tab.id} connectionId={tab.connectionId} />;
              }
              if (tab.kind === "ermodel") {
                return <ErModel key={tab.id} connectionId={tab.connectionId} database={tab.database} />;
              }
              if (tab.kind === "object") {
                return <ObjectDesigner key={tab.id} connectionId={tab.connectionId} database={tab.database} />;
              }
              if (tab.kind === "scheduler") {
                return <Scheduler key={tab.id} connections={connections.map((c) => ({ id: c.id, name: c.name }))} />;
              }
                return (
                  <QueryEditor
                    key={tab.id}
                    connectionId={tab.connectionId}
                    database={tab.database}
                    table={tab.table}
                    initialSql={tab.initialSql}
                  />
                );
              })}
            </>
          )}
        </div>
        {showAi && (
          <AiPanel
            onSqlGenerated={onSqlGenerated}
          />
        )}
      </div>
      {showSettings && <SettingsDialog onClose={() => { setShowSettings(false); const l: Lang = (localStorage.getItem("opennavicat_language") as Lang) || "zh"; setLang(l); }} />}
    </div>
    </I18nCtx.Provider>
  );
}

export default App;
