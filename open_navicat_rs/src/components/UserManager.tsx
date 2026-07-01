import { useState, useEffect } from "react";
import { listUsers, createUser, dropUser, type UserInfo } from "../api/commands";

interface Props {
  connectionId: string;
}

export default function UserManager({ connectionId }: Props) {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [newUser, setNewUser] = useState({ username: "", host: "%", password: "" });
  const [result, setResult] = useState("");

  const reload = async () => {
    setLoading(true);
    try {
      const u = await listUsers(connectionId);
      setUsers(u);
    } catch (e) { setResult(String(e)); }
    setLoading(false);
  };

  useEffect(() => { reload(); }, [connectionId]);

  const handleCreate = async () => {
    if (!newUser.username || !newUser.password) return;
    setResult("");
    try {
      await createUser(connectionId, newUser.username, newUser.host, newUser.password);
      setNewUser({ username: "", host: "%", password: "" });
      await reload();
      setResult(`用户 ${newUser.username}@${newUser.host} 创建成功`);
    } catch (e) { setResult(String(e)); }
  };

  const handleDrop = async (username: string, host: string) => {
    if (!confirm(`确认删除用户 ${username}@${host}?`)) return;
    setResult("");
    try {
      await dropUser(connectionId, username, host);
      await reload();
      setResult(`用户 ${username}@${host} 已删除`);
    } catch (e) { setResult(String(e)); }
  };

  if (loading) return <div className="struct-loading">加载中...</div>;

  return (
    <div className="backup-panel">
      <div className="struct-section">
        <div className="struct-section-title">用户管理</div>
        <table className="struct-table">
          <thead><tr><th>用户名</th><th>主机</th><th>认证方式</th><th>操作</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={`${u.user}@${u.host}`}>
                <td className="cell-name">{u.user}</td>
                <td>{u.host}</td>
                <td style={{ fontSize: 11 }}>{u.plugin}</td>
                <td><button className="designer-btn danger" onClick={() => handleDrop(u.user, u.host)}>删除</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="struct-section">
        <div className="struct-section-title">创建用户</div>
        <div className="designer-form">
          <input placeholder="用户名" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} />
          <input placeholder="主机 (默认 %)" value={newUser.host} onChange={(e) => setNewUser({ ...newUser, host: e.target.value })} />
          <input placeholder="密码" type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} />
          <button className="designer-btn primary" onClick={handleCreate}>创建用户</button>
        </div>
      </div>

      {result && <pre className="struct-ddl">{result}</pre>}
    </div>
  );
}
