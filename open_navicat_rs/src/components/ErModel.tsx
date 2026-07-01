import { useState, useCallback, useEffect } from "react";
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, type Node, type Edge, Handle, Position } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { listTables, listColumns, listForeignKeys } from "../api/commands";

interface Props { connectionId: string; database: string; }

type TableNodeData = Record<string, unknown> & { label: string; columns: Array<{ name: string; type: string; pk: boolean }> };

function TableNode({ data }: { data: Record<string, unknown> }) {
  const d = data as unknown as TableNodeData;
  return (
    <div style={{ background: "#1e1e2e", border: "1px solid #45475a", borderRadius: 6, minWidth: 180, fontSize: 11 }}>
      <div style={{ background: "#45475a", color: "#cdd6f4", padding: "6px 10px", fontWeight: 700, borderRadius: "6px 6px 0 0", borderBottom: "1px solid #585b70" }}>
        <Handle type="target" position={Position.Left} style={{ background: "#89b4fa" }} />
        {d.label}
        <Handle type="source" position={Position.Right} style={{ background: "#89b4fa" }} />
      </div>
      <div style={{ padding: "2px 0" }}>
        {d.columns.map((col, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 4, padding: "3px 10px", borderBottom: i < d.columns.length - 1 ? "1px solid #313244" : "none" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: col.pk ? "#f9e2af" : "#6c7086", flexShrink: 0 }} />
            <span style={{ color: col.pk ? "#f9e2af" : "#bac2de", fontWeight: col.pk ? 700 : 400 }}>{col.name}</span>
            <span style={{ color: "#6c7086", marginLeft: "auto", fontSize: 10 }}>{col.type}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const nodeTypes = { tableNode: TableNode };

export default function ErModel({ connectionId, database }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadSchema = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const tables = await listTables(connectionId, database);
      const cols = await Promise.all(tables.map((t) => listColumns(connectionId, database, t.name)));
      const fks = await Promise.all(tables.map((t) => listForeignKeys(connectionId, database, t.name)));
      const gapX = 280;
      const cpr = Math.ceil(Math.sqrt(tables.length));
      const flowNodes: Node[] = tables.map((t, i) => ({
        id: t.name, type: "tableNode",
        position: { x: (i % cpr) * gapX + 20, y: Math.floor(i / cpr) * 80 + 50 },
        data: { label: t.name, columns: cols[i].map((c) => ({ name: c.name, type: c.data_type, pk: c.is_primary_key })) },
      }));
      const flowEdges: Edge[] = [];
      tables.forEach((t, ti) => fks[ti].forEach((fk) => {
        if (flowNodes.some((n) => n.id === fk.ref_table)) {
          flowEdges.push({ id: "fk-"+t.name+"-"+fk.name, source: t.name, target: fk.ref_table, label: fk.column+" → "+fk.ref_column, style: { stroke: "#fab387", strokeWidth: 1.5 }, animated: true });
        }
      }));
      setNodes(flowNodes); setEdges(flowEdges);
    } catch (e) { setError(String(e)); }
    setLoading(false);
  }, [connectionId, database]);

  useEffect(() => { loadSchema(); }, [loadSchema]);

  return (
    <div style={{ flex: 1, position: "relative" }}>
      <div style={{ position: "absolute", top: 8, right: 8, zIndex: 10 }}>
        <button className="struct-btn" onClick={loadSchema} style={{ fontSize: 11 }}>🔄 刷新</button>
      </div>
      {loading ? <div className="struct-loading">加载中...</div> : error ? <div className="error-msg">{error}</div> : (
        <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} nodeTypes={nodeTypes} fitView>
          <Background />
          <Controls />
          <MiniMap style={{ background: "#1e1e2e" }} />
        </ReactFlow>
      )}
    </div>
  );
}
