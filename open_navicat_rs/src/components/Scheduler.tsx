import { useState, useEffect, useRef } from "react";
import { backupDatabase } from "../api/commands";

interface Schedule {
  id: string;
  name: string;
  connectionId: string;
  database: string;
  frequency: "once" | "hourly" | "daily" | "weekly" | "monthly";
  nextRun: string;
  lastRun: string | null;
  lastResult: string | null;
}

interface Props { connections: { id: string; name: string }[]; }

export default function Scheduler({ connections }: Props) {
  const [schedules, setSchedules] = useState<Schedule[]>(() => {
    try { return JSON.parse(localStorage.getItem("opennavicat_schedules") || "[]"); } catch { return []; }
  });
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<{ name: string; connectionId: string; database: string; frequency: Schedule["frequency"] }>({ name: "", connectionId: "", database: "", frequency: "daily" });
  const [running, setRunning] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);

  useEffect(() => { localStorage.setItem("opennavicat_schedules", JSON.stringify(schedules)); }, [schedules]);

  const calcNextRun = (freq: string): string => {
    const d = new Date();
    if (freq === "once") return d.toISOString();
    if (freq === "hourly") { d.setHours(d.getHours() + 1); return d.toISOString(); }
    if (freq === "daily") { d.setDate(d.getDate() + 1); return d.toISOString(); }
    if (freq === "weekly") { d.setDate(d.getDate() + 7); return d.toISOString(); }
    d.setMonth(d.getMonth() + 1); return d.toISOString();
  };

  const addSchedule = () => {
    if (!form.name || !form.connectionId) return;
    const s: Schedule = { id: crypto.randomUUID(), ...form, nextRun: calcNextRun(form.frequency), lastRun: null, lastResult: null };
    setSchedules((p) => [...p, s]);
    setShowForm(false); setForm({ name: "", connectionId: "", database: "", frequency: "daily" });
  };

  const deleteSchedule = (id: string) => setSchedules((p) => p.filter((s) => s.id !== id));

  const runSchedule = async (s: Schedule) => {
    setRunning(s.id);
    try {
      const ts = new Date().toISOString().replace(/[:.]/g, "-");
      const outPath = `${s.database}_${ts}.sql`;
      const result = await backupDatabase(s.connectionId, outPath, true);
      setSchedules((p) => p.map((x) => x.id === s.id ? { ...x, lastRun: new Date().toISOString(), lastResult: result, nextRun: calcNextRun(x.frequency) } : x));
      setLog((p) => [...p.slice(-99), `[${new Date().toLocaleString()}] ${s.name}: 成功 → ${result}`]);
    } catch (e) {
      setSchedules((p) => p.map((x) => x.id === s.id ? { ...x, lastRun: new Date().toISOString(), lastResult: String(e) } : x));
      setLog((p) => [...p.slice(-99), `[${new Date().toLocaleString()}] ${s.name}: 失败 → ${e}`]);
    }
    setRunning(null);
  };

  // auto-check every 30s
  const intervalRef = useRef<ReturnType<typeof setInterval>>();
  useEffect(() => {
    intervalRef.current = setInterval(() => {
      const now = new Date().getTime();
      setSchedules((prev) => {
        const updated = prev.map((s) => {
          if (s.nextRun && new Date(s.nextRun).getTime() <= now) {
            runSchedule(s);
            return { ...s };
          }
          return s;
        });
        return updated;
      });
    }, 30000);
    return () => clearInterval(intervalRef.current!);
  }, []);

  return (
    <div style={{ display: "flex", flex: 1, gap: 8, padding: 8, overflow: "hidden" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: "#a6adc8", fontWeight: 700 }}>备份调度</span>
          <button className="struct-btn" onClick={() => setShowForm(true)} style={{ fontSize: 11 }}>+ 新建</button>
          <span style={{ color: "#6c7086", fontSize: 11 }}>每 30 秒自动检查，仅应用运行时生效</span>
        </div>
        {showForm && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", padding: 8, border: "1px solid #45475a", borderRadius: 4 }}>
            <input placeholder="名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={{ width: 120 }} />
            <select value={form.connectionId} onChange={(e) => setForm({ ...form, connectionId: e.target.value })}
              style={{ width: 120, background: "#1e1e2e", color: "#cdd6f4", border: "1px solid #45475a", borderRadius: 4 }}>
              <option value="">选择连接</option>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <input placeholder="数据库" value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })} style={{ width: 100 }} />
            <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value as Schedule["frequency"] })}
              style={{ width: 90, background: "#1e1e2e", color: "#cdd6f4", border: "1px solid #45475a", borderRadius: 4 }}>
              <option value="once">一次</option><option value="hourly">每小时</option><option value="daily">每天</option>
              <option value="weekly">每周</option><option value="monthly">每月</option>
            </select>
            <button className="struct-btn" onClick={addSchedule} style={{ fontSize: 11 }}>保存</button>
            <button className="struct-btn" onClick={() => setShowForm(false)} style={{ fontSize: 11 }}>取消</button>
          </div>
        )}
        {schedules.length === 0 ? <div className="struct-loading">暂无调度</div> : (
          <table className="result-table">
            <thead><tr><th>名称</th><th>连接</th><th>数据库</th><th>频率</th><th>下次执行</th><th>上次结果</th><th>操作</th></tr></thead>
            <tbody>
              {schedules.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td><td>{connections.find((c) => c.id === s.connectionId)?.name || "?"}</td>
                  <td>{s.database}</td>
                  <td>{s.frequency === "once" ? "一次" : s.frequency === "hourly" ? "每小时" : s.frequency === "daily" ? "每天" : s.frequency === "weekly" ? "每周" : "每月"}</td>
                  <td style={{ fontSize: 11 }}>{s.nextRun ? new Date(s.nextRun).toLocaleString() : "-"}</td>
                  <td style={{ fontSize: 11, color: s.lastResult?.includes("失败") ? "#f38ba8" : s.lastResult ? "#a6e3a1" : "#6c7086" }}>
                    {running === s.id ? "运行中..." : s.lastResult ? (s.lastResult.length > 40 ? s.lastResult.slice(0, 40)+"…" : s.lastResult) : "-"}
                  </td>
                  <td>
                    <button className="struct-btn" onClick={() => runSchedule(s)} disabled={running === s.id} style={{ fontSize: 11 }}>▶</button>
                    <button className="struct-btn" onClick={() => deleteSchedule(s.id)} style={{ fontSize: 11 }}>×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div style={{ width: 300, display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ color: "#a6adc8", fontWeight: 700, fontSize: 12 }}>执行日志</span>
        <div style={{ flex: 1, overflowY: "auto", border: "1px solid #45475a", borderRadius: 4, padding: 4, fontSize: 11, color: "#a6adc8", background: "#11111b" }}>
          {log.length === 0 ? <span style={{ color: "#6c7086" }}>无日志</span> : log.map((l, i) => <div key={i}>{l}</div>)}
        </div>
      </div>
    </div>
  );
}
