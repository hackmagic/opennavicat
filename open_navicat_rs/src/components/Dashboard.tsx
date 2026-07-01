import { useState, useEffect } from "react";
import { executeQuery } from "../api/commands";
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, PointElement, LineElement, ArcElement, Title, Tooltip, Legend, Filler } from "chart.js";
import { Bar, Line, Pie } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, ArcElement, Title, Tooltip, Legend, Filler);

const DASH_KEY = "opennavicat_dashboard_widgets";

interface Widget {
  id: string;
  title: string;
  sql: string;
  chartType: "bar" | "line" | "pie";
  labelsCol: number;
  dataCol: number;
}

interface Props {
  connectionId: string;
}

function loadWidgets(): Widget[] {
  try { return JSON.parse(localStorage.getItem(DASH_KEY) || "[]"); } catch { return []; }
}
function saveWidgets(w: Widget[]) { localStorage.setItem(DASH_KEY, JSON.stringify(w)); }

export default function Dashboard({ connectionId }: Props) {
  const [widgets, setWidgets] = useState<Widget[]>(loadWidgets);
  const [chartData, setChartData] = useState<Record<string, { labels: string[]; values: number[] } | null>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<Partial<Widget> | null>(null);

  useEffect(() => { saveWidgets(widgets); }, [widgets]);

  const runWidget = async (w: Widget) => {
    const r = await executeQuery(connectionId, w.sql);
    if (r.error) { setErrors((e) => ({ ...e, [w.id]: r.error! })); return; }
    setErrors((e) => { const c = { ...e }; delete c[w.id]; return c; });
    const labels = r.rows.map((row) => String(row[w.labelsCol] ?? ""));
    const values = r.rows.map((row) => Number(row[w.dataCol]) || 0);
    setChartData((d) => ({ ...d, [w.id]: { labels, values } }));
  };

  useEffect(() => {
    if (!connectionId) return;
    widgets.forEach((w) => runWidget(w));
  }, [connectionId]);

  const addWidget = () => {
    if (!editing?.title || !editing?.sql) return;
    const w: Widget = {
      id: crypto.randomUUID(),
      title: editing.title!,
      sql: editing.sql!,
      chartType: editing.chartType || "bar",
      labelsCol: editing.labelsCol ?? 0,
      dataCol: editing.dataCol ?? 1,
    };
    setWidgets((prev) => [...prev, w]);
    setEditing(null);
    runWidget(w);
  };

  const delWidget = (id: string) => {
    setWidgets((prev) => prev.filter((w) => w.id !== id));
    setChartData((d) => { const c = { ...d }; delete c[id]; return c; });
  };

  const colors = ["#89b4fa", "#a6e3a1", "#f9e2af", "#fab387", "#cba6f7", "#f38ba8", "#94e2d5", "#b4befe"];

  return (
    <div className="backup-panel">
      <div className="struct-section">
        <div className="struct-section-title">BI 仪表盘</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
          <button className="designer-btn primary" onClick={() => setEditing({ chartType: "bar" })}>+ 添加图表</button>
        </div>

        {editing && (
          <div className="designer-form" style={{ marginBottom: 12 }}>
            <input placeholder="标题" value={editing.title || ""} onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
            <input placeholder="SQL (SELECT 两列: 标签, 值)" value={editing.sql || ""} onChange={(e) => setEditing({ ...editing, sql: e.target.value })} style={{ flex: 2 }} />
            <select value={editing.chartType} onChange={(e) => setEditing({ ...editing, chartType: e.target.value as any })}>
              <option value="bar">柱状图</option>
              <option value="line">折线图</option>
              <option value="pie">饼图</option>
            </select>
            <input type="number" placeholder="标签列" value={editing.labelsCol ?? 0} onChange={(e) => setEditing({ ...editing, labelsCol: Number(e.target.value) })} style={{ width: 50 }} />
            <input type="number" placeholder="数据列" value={editing.dataCol ?? 1} onChange={(e) => setEditing({ ...editing, dataCol: Number(e.target.value) })} style={{ width: 50 }} />
            <button className="designer-btn primary" onClick={addWidget}>添加</button>
            <button className="designer-btn" onClick={() => setEditing(null)}>取消</button>
          </div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(350px, 1fr))", gap: 12 }}>
        {widgets.map((w) => {
          const data = chartData[w.id];
          return (
            <div key={w.id} className="struct-section" style={{ position: "relative" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div className="struct-section-title">{w.title}</div>
                <button className="struct-btn" onClick={() => delWidget(w.id)} style={{ border: "1px solid var(--red)", color: "var(--red)" }}>✕</button>
              </div>
              {errors[w.id] && <div className="error-msg" style={{ fontSize: 11 }}>{errors[w.id]}</div>}
              {data ? (
                <div style={{ height: 250 }}>
                  {w.chartType === "pie" ? (
                    <Pie data={{
                      labels: data.labels,
                      datasets: [{ data: data.values, backgroundColor: colors.slice(0, data.labels.length) }],
                    }} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { color: "#cdd6f4", font: { size: 10 } } } } }} />
                  ) : w.chartType === "line" ? (
                    <Line data={{
                      labels: data.labels,
                      datasets: [{ label: w.title, data: data.values, borderColor: colors[0], backgroundColor: colors[0] + "40", fill: true, tension: 0.3, pointRadius: 3 }],
                    }} options={{ responsive: true, maintainAspectRatio: false, scales: { x: { ticks: { color: "#a6adc8", font: { size: 10 } } }, y: { ticks: { color: "#a6adc8", font: { size: 10 } } } }, plugins: { legend: { display: false } } }} />
                  ) : (
                    <Bar data={{
                      labels: data.labels,
                      datasets: [{ label: w.title, data: data.values, backgroundColor: colors.slice(0, data.labels.length), borderRadius: 4 }],
                    }} options={{ responsive: true, maintainAspectRatio: false, scales: { x: { ticks: { color: "#a6adc8", font: { size: 10 } } }, y: { ticks: { color: "#a6adc8", font: { size: 10 } } } }, plugins: { legend: { display: false } } }} />
                  )}
                </div>
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 40, textAlign: "center" }}>加载中...</div>
              )}
            </div>
          );
        })}
      </div>

      {widgets.length === 0 && !editing && (
        <div style={{ color: "var(--text-muted)", textAlign: "center", padding: 40, fontSize: 13 }}>
          点击"+ 添加图表"开始构建仪表盘<br />
          <small>SQL 应返回至少两列: 标签列 + 数值列</small>
        </div>
      )}
    </div>
  );
}
