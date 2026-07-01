import { useState } from "react";
import { backupDatabase, restoreDatabase } from "../api/commands";

interface Props {
  connectionId: string;
  database: string;
}

export default function BackupRestore({ connectionId, database }: Props) {
  const [outputName, setOutputName] = useState(`backup_${database}_${new Date().toISOString().slice(0, 10)}.sql`);
  const [includeRoutines, setIncludeRoutines] = useState(true);
  const [backingUp, setBackingUp] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [backupResult, setBackupResult] = useState("");
  const [restorePath, setRestorePath] = useState("");
  const [restoreResult, setRestoreResult] = useState("");

  const doBackup = async () => {
    setBackingUp(true);
    setBackupResult("");
    try {
      const path = await backupDatabase(connectionId, outputName, includeRoutines);
      setBackupResult(`备份成功: ${path}`);
    } catch (e) {
      setBackupResult(`备份失败: ${e}`);
    }
    setBackingUp(false);
  };

  const doRestore = async () => {
    if (!restorePath.trim()) return;
    setRestoring(true);
    setRestoreResult("");
    try {
      const msg = await restoreDatabase(connectionId, restorePath);
      setRestoreResult(msg);
    } catch (e) {
      setRestoreResult(`恢复失败: ${e}`);
    }
    setRestoring(false);
  };

  return (
    <div className="backup-panel">
      <div className="struct-section">
        <div className="struct-section-title">备份数据库</div>
        <div className="designer-form">
          <input value={outputName} onChange={(e) => setOutputName(e.target.value)} style={{ flex: 1 }} placeholder="输出文件名" />
          <label className="designer-checkbox"><input type="checkbox" checked={includeRoutines} onChange={(e) => setIncludeRoutines(e.target.checked)} /> 包含存储过程/触发器等</label>
          <button className="designer-btn primary" onClick={doBackup} disabled={backingUp}>{backingUp ? "备份中..." : "开始备份"}</button>
        </div>
        {backupResult && <pre className="struct-ddl">{backupResult}</pre>}
      </div>

      <div className="struct-section">
        <div className="struct-section-title">恢复数据库</div>
        <div className="designer-form">
          <input value={restorePath} onChange={(e) => setRestorePath(e.target.value)} style={{ flex: 1 }} placeholder="SQL 文件路径" />
          <button className="designer-btn primary" onClick={doRestore} disabled={restoring}>{restoring ? "恢复中..." : "开始恢复"}</button>
        </div>
        {restoreResult && <pre className="struct-ddl">{restoreResult}</pre>}
      </div>
    </div>
  );
}
