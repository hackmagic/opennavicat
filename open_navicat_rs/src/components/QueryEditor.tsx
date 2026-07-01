import { useState, useCallback, useEffect, useRef } from "react";
import { executeQuery, updateCell, listColumns, type QueryResult } from "../api/commands";

const HISTORY_KEY = "opennavicat_query_history";
const SAVED_KEY = "opennavicat_saved_queries";
const HISTORY_MAX = 50;

function loadHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
  } catch { return []; }
}

function saveHistoryEntry(sql: string) {
  const h = loadHistory().filter((s) => s !== sql);
  h.unshift(sql);
  if (h.length > HISTORY_MAX) h.length = HISTORY_MAX;
  localStorage.setItem(HISTORY_KEY, JSON.stringify(h));
}

interface Props {
  connectionId: string;
  database: string;
  initialSql?: string;
  table?: string;
}

export default function QueryEditor({ connectionId, database, initialSql, table }: Props) {
  const [sql, setSql] = useState(initialSql || "SELECT * FROM `table` LIMIT 100;");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const ran = useRef(false);
  const historyRef = useRef<HTMLDivElement>(null);

  // pagination
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(100);
  const [totalRows, setTotalRows] = useState<number | null>(null);

  // sort & filter
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"ASC" | "DESC">("ASC");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [showFilters, setShowFilters] = useState(false);

  const isTableMode = !!table;

  const buildTableQuery = useCallback((pg: number, ps: number): string => {
    if (!table) return "";
    const where = Object.entries(filters)
      .filter(([, v]) => v)
      .map(([k, v]) => `${k} LIKE '%${v.replace(/'/g, "''")}%'`)
      .join(" AND ");
    const order = sortCol ? ` ORDER BY ${sortCol} ${sortDir}` : "";
    const wc = where ? ` WHERE ${where}` : "";
    return `SELECT * FROM ${table}${wc}${order} LIMIT ${ps} OFFSET ${pg * ps}`;
  }, [table, sortCol, sortDir, filters]);

  // inline editing
  const [editing, setEditing] = useState<{ row: number; col: number } | null>(null);
  const [editVal, setEditVal] = useState("");

  // saved queries
  const [savedQueries, setSavedQueries] = useState<{ name: string; sql: string }[]>(() => {
    try { return JSON.parse(localStorage.getItem(SAVED_KEY) || "[]"); } catch { return []; }
  });
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [saveName, setSaveName] = useState("");

  const doSaveQuery = () => {
    if (!saveName.trim()) return;
    const updated = [...savedQueries.filter((q) => q.name !== saveName), { name: saveName, sql }];
    localStorage.setItem(SAVED_KEY, JSON.stringify(updated));
    setSavedQueries(updated);
    setShowSaveDialog(false);
    setSaveName("");
  };

  const doDeleteSaved = (name: string) => {
    const updated = savedQueries.filter((q) => q.name !== name);
    localStorage.setItem(SAVED_KEY, JSON.stringify(updated));
    setSavedQueries(updated);
  };

  // query history
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<string[]>([]);

  useEffect(() => {
    setHistory(loadHistory());
    const handle = (e: MouseEvent) => {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setShowHistory(false);
      }
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  const runSql = useCallback(async (sqlText: string) => {
    setLoading(true);
    const r = await executeQuery(connectionId, sqlText);
    setResult(r);
    setLoading(false);
    return r;
  }, [connectionId]);

  useEffect(() => {
    if (initialSql && !ran.current && isTableMode) {
      ran.current = true;
      const q = buildTableQuery(0, pageSize);
      runSql(q).then((r) => {
        if (!r.error) {
          const countSql = `SELECT COUNT(*) AS cnt FROM ${table}`;
          executeQuery(connectionId, countSql).then((cr) => {
            if (!cr.error && cr.rows.length > 0) setTotalRows(Number(cr.rows[0][0]));
          }).catch(() => {});
        }
      });
    }
  }, []);

  const run = useCallback(async () => {
    setPage(0);
    setEditing(null);
    const r = await runSql(sql);
    if (!r.error) {
      saveHistoryEntry(sql);
      setHistory(loadHistory());
      if (table) {
        const countSql = `SELECT COUNT(*) AS cnt FROM ${table}`;
        executeQuery(connectionId, countSql).then((cr) => {
          if (!cr.error && cr.rows.length > 0) {
            setTotalRows(Number(cr.rows[0][0]));
          }
        }).catch(() => {});
      }
    }
  }, [connectionId, sql, table, runSql]);

  const goPage = async (dir: number) => {
    const newPage = page + dir;
    if (newPage < 0 || !isTableMode) return;
    setPage(newPage);
    setEditing(null);
    await runSql(buildTableQuery(newPage, pageSize));
  };

  const refreshTable = useCallback(async () => {
    if (!isTableMode) return;
    setPage(0);
    setEditing(null);
    const q = buildTableQuery(0, pageSize);
    const r = await runSql(q);
    if (!r.error) {
      const countSql = `SELECT COUNT(*) AS cnt FROM ${table}`;
      executeQuery(connectionId, countSql).then((cr) => {
        if (!cr.error && cr.rows.length > 0) setTotalRows(Number(cr.rows[0][0]));
      }).catch(() => {});
    }
  }, [isTableMode, table, buildTableQuery, pageSize, runSql, connectionId]);

  const cellValue = (v: unknown): string => {
    if (v === null || v === undefined) return "NULL";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  };

  const downloadBlob = (blob: Blob, name: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportCsv = () => {
    if (!result || result.error) return;
    const esc = (s: string) => '"' + s.replace(/"/g, '""') + '"';
    const header = result.columns.map(esc).join(",");
    const rows = result.rows.map((r) => r.map((c) => esc(cellValue(c))).join(","));
    downloadBlob(new Blob(["\uFEFF" + header + "\n" + rows.join("\n")], { type: "text/csv;charset=utf-8;bom" }), `query_${Date.now()}.csv`);
  };

  const exportJson = () => {
    if (!result || result.error) return;
    const data = result.rows.map((r) => {
      const obj: Record<string, unknown> = {};
      result.columns.forEach((col, i) => { obj[col] = r[i]; });
      return obj;
    });
    downloadBlob(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }), `query_${Date.now()}.json`);
  };

  const exportXlsx = async () => {
    if (!result || result.error) return;
    const XLSX = await import("xlsx");
    const data = [result.columns, ...result.rows.map((r) => r.map((c) => cellValue(c)))];
    const ws = XLSX.utils.aoa_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
    const buf = XLSX.write(wb, { bookType: "xlsx", type: "array" });
    downloadBlob(new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), `query_${Date.now()}.xlsx`);
  };

  const exportInsertSql = () => {
    if (!result || result.error) return;
    const colList = result.columns.map((c) => `\`${c}\``).join(", ");
    const lines = result.rows.map((r) => {
      const vals = r.map((c) => {
        if (c === null || c === undefined) return "NULL";
        if (typeof c === "number") return String(c);
        return `'${String(c).replace(/'/g, "''")}'`;
      }).join(", ");
      return `INSERT INTO \`${table || "result"}\` (${colList}) VALUES (${vals});`;
    });
    downloadBlob(new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" }), `query_${Date.now()}.sql`);
  };

  const exportMarkdown = () => {
    if (!result || result.error) return;
    const sep = "| " + result.columns.map(() => "---").join(" | ") + " |";
    const header = "| " + result.columns.join(" | ") + " |";
    const rows = result.rows.map((r) => "| " + r.map((c) => cellValue(c)).join(" | ") + " |");
    downloadBlob(new Blob([header + "\n" + sep + "\n" + rows.join("\n")], { type: "text/markdown;charset=utf-8" }), `query_${Date.now()}.md`);
  };

  const startEdit = (rowIdx: number, colIdx: number) => {
    if (!result || result.error || !table) return;
    setEditing({ row: rowIdx, col: colIdx });
    setEditVal(cellValue(result.rows[rowIdx][colIdx]));
  };

  const saveEdit = async () => {
    if (!editing || !result || !table) return;
    const { row, col } = editing;
    const colName = result.columns[col];
    const rowData = result.rows[row];
    let pkIdx = -1;
    try {
      const cols = await listColumns(connectionId, database, table);
      pkIdx = cols.findIndex((c) => c.is_primary_key);
    } catch { /* fallback to first column */ }
    if (pkIdx < 0) pkIdx = 0;
    const pkCol = result.columns[pkIdx];
    const pkValue = cellValue(rowData[pkIdx]);
    const newValue = editVal === "NULL" || editVal === "" ? null : editVal;

    setLoading(true);
    try {
      await updateCell(connectionId, database, table, colName, newValue, pkCol, pkValue);
      const updated = [...result.rows];
      updated[row] = [...updated[row]];
      updated[row][col] = newValue;
      setResult({ ...result, rows: updated });
    } catch (e) {
      alert(String(e));
    }
    setLoading(false);
    setEditing(null);
  };

  const cancelEdit = () => {
    setEditing(null);
  };

  const totalPages = totalRows !== null ? Math.ceil(totalRows / pageSize) : 0;

  // refresh on sort/filter/pageSize change
  useEffect(() => {
    if (ran.current && isTableMode) {
      refreshTable();
    }
  }, [sortCol, sortDir, filters, pageSize]);

  const toggleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "ASC" ? "DESC" : "ASC"));
    } else {
      setSortCol(col);
      setSortDir("ASC");
    }
  };

  const setFilter = (col: string, val: string) => {
    setFilters((prev) => ({ ...prev, [col]: val }));
  };

  return (
    <div className="query-editor">
      <div className="editor-toolbar">
        <select className="db-select" value={database} onChange={() => {}}>
          <option>{database}</option>
        </select>
        <button className="run-btn" onClick={run} disabled={loading}>
          {loading ? "执行中..." : "▶ 执行"}
        </button>
        <div className="history-wrap" ref={historyRef}>
          <button className="history-btn" onClick={() => setShowHistory(!showHistory)} disabled={history.length === 0}>
            ⌛ 历史
          </button>
          {showHistory && (
            <div className="history-dropdown">
              <div className="history-header">最近查询</div>
              {history.map((h, i) => (
                <div
                  key={i}
                  className="history-item"
                  onClick={() => { setSql(h); setShowHistory(false); }}
                >
                  <code>{h}</code>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="saved-wrap">
          <button className="save-btn" onClick={() => setShowSaveDialog(true)} disabled={!sql.trim()}>💾 保存</button>
          {savedQueries.length > 0 && (
            <select className="saved-select" defaultValue="" onChange={(e) => {
              const val = e.target.value;
              if (val.startsWith("__load__")) setSql(val.slice(8));
              else if (val.startsWith("__del__")) doDeleteSaved(val.slice(7));
            }}>
              <option value="" disabled>已保存查询...</option>
              {savedQueries.map((q) => (
                <option key={q.name} value={`__load__${q.sql}`}>{q.name}</option>
              ))}
              <option disabled>──────────</option>
              {savedQueries.map((q) => (
                <option key={`del-${q.name}`} value={`__del__${q.name}`}>🗑 删除 {q.name}</option>
              ))}
            </select>
          )}
        </div>
        {showSaveDialog && (
          <div className="save-dialog-overlay" onClick={() => setShowSaveDialog(false)}>
            <div className="save-dialog" onClick={(e) => e.stopPropagation()}>
              <input value={saveName} onChange={(e) => setSaveName(e.target.value)} placeholder="查询名称" autoFocus onKeyDown={(e) => e.key === "Enter" && doSaveQuery()} />
              <button onClick={doSaveQuery}>保存</button>
              <button onClick={() => setShowSaveDialog(false)}>取消</button>
            </div>
          </div>
        )}
      </div>

      {!isTableMode && (
        <textarea
          className="sql-input"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          placeholder="输入 SQL 语句..."
          spellCheck={false}
        />
      )}

      {result && (
        <div className="result-area">
          <div className="result-toolbar">
            <span>
              {result.error ? "错误" : `返回 ${result.rows_affected} 行 | ${result.execution_time_ms}ms`}
            </span>
            {table && totalRows !== null && (
              <span className="pagination">
                <button className="page-btn" onClick={() => goPage(-1)} disabled={page <= 0}>‹</button>
                <span className="page-info">{page + 1}/{totalPages || 1}</span>
                <button className="page-btn" onClick={() => goPage(1)} disabled={page + 1 >= totalPages}>›</button>
                <select className="page-size" value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); }}>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                  <option value={200}>200</option>
                  <option value={500}>500</option>
                </select>
              </span>
            )}
            {!result.error && (
              <>
                {isTableMode && (
                  <button className="filter-btn" onClick={() => setShowFilters((s) => !s)}>
                    🔍 过滤
                  </button>
                )}
                <button className="export-btn" onClick={exportInsertSql} title="导出 INSERT SQL">SQL</button>
                <button className="export-btn" onClick={exportMarkdown} title="导出 Markdown">MD</button>
                <button className="export-btn" onClick={exportJson} title="导出 JSON">JSON</button>
                <button className="export-btn" onClick={exportXlsx} title="导出 Excel">XLSX</button>
                <button className="export-btn csv" onClick={exportCsv} title="导出 CSV">CSV</button>
              </>
            )}
          </div>

          {result.error ? (
            <div className="error-msg">{result.error}</div>
          ) : (
            <div className="result-table-wrapper">
              <table className="result-table">
                <thead>
                  <tr>
                    {result.columns.map((col, i) => (
                      <th key={i} onClick={() => isTableMode && toggleSort(col)} className={isTableMode ? "sortable" : ""}>
                        {col}
                        {sortCol === col && <span className="sort-icon">{sortDir === "ASC" ? " ▲" : " ▼"}</span>}
                      </th>
                    ))}
                  </tr>
                  {isTableMode && showFilters && (
                    <tr className="filter-row">
                      {result.columns.map((col, i) => (
                        <th key={i}>
                          <input
                            className="filter-input"
                            value={filters[col] || ""}
                            onChange={(e) => setFilter(col, e.target.value)}
                            placeholder="过滤..."
                          />
                        </th>
                      ))}
                    </tr>
                  )}
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => {
                        const isEditing = editing && editing.row === i && editing.col === j;
                        return (
                          <td key={j} onDoubleClick={() => startEdit(i, j)} className={isEditing ? "editing" : ""}>
                            {isEditing ? (
                              <span className="edit-cell">
                                <input
                                  className="edit-input"
                                  value={editVal}
                                  onChange={(e) => setEditVal(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") saveEdit();
                                    if (e.key === "Escape") cancelEdit();
                                  }}
                                  autoFocus
                                />
                                <button className="edit-save" onClick={saveEdit}>✓</button>
                                <button className="edit-cancel" onClick={cancelEdit}>✗</button>
                              </span>
                            ) : (
                              cellValue(cell)
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
