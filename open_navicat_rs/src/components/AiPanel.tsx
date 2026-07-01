import { useState, useEffect, useRef } from "react";

interface AiConfig {
  provider: string; // openai | deepseek | ollama | custom
  apiKey: string;
  apiBase: string;
  model: string;
}

const CONFIG_KEY = "opennavicat_ai_config";

function loadConfig(): AiConfig {
  try {
    return JSON.parse(localStorage.getItem(CONFIG_KEY) || "null") || defaultConfig();
  } catch { return defaultConfig(); }
}

function saveConfig(c: AiConfig) {
  localStorage.setItem(CONFIG_KEY, JSON.stringify(c));
}

function defaultConfig(): AiConfig {
  return { provider: "deepseek", apiKey: "", apiBase: "https://api.deepseek.com", model: "deepseek-chat" };
}

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface Props {
  schemaContext?: string;
  onSqlGenerated: (sql: string) => void;
}

export default function AiPanel({ schemaContext, onSqlGenerated }: Props) {
  const [config, setConfig] = useState<AiConfig>(loadConfig);
  const [showConfig, setShowConfig] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView(); }, [messages]);

  const send = async () => {
    if (!input.trim() || busy) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setBusy(true);

    const sysPrompt = schemaContext
      ? `你是数据库助手。数据库结构：\n${schemaContext}\n用户会问关于数据的问题，返回 SQL 查询和简要说明。`
      : "你是数据库助手。帮助用户编写 SQL 查询。返回 SQL 和简要说明。";

    const body = {
      model: config.model,
      messages: [
        { role: "system", content: sysPrompt },
        ...messages.map((m) => ({ role: m.role, content: m.content })),
        { role: "user", content: userMsg },
      ],
      stream: true,
    };

    try {
      const baseUrl = config.apiBase.replace(/\/+$/, "");
      const res = await fetch(`${baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${config.apiKey}`,
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.text().catch(() => "");
        setMessages((prev) => [...prev, { role: "assistant", content: `错误 ${res.status}: ${err}` }]);
        setBusy(false);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) { setBusy(false); return; }

      const decoder = new TextDecoder();
      let fullText = "";
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") break;
          try {
            const json = JSON.parse(data);
            const delta = json.choices?.[0]?.delta?.content || "";
            fullText += delta;
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { role: "assistant", content: fullText };
              return next;
            });
          } catch {}
        }
      }
    } catch (e) {
      setMessages((prev) => [...prev, { role: "assistant", content: `请求失败: ${e}` }]);
    }
    setBusy(false);
  };

  const extractSql = (text: string): string => {
    const m = text.match(/```sql\n([\s\S]*?)```/);
    return m ? m[1].trim() : text;
  };

  return (
    <div className="ai-panel">
      <div className="ai-header">
        <span>AI 助手</span>
        <button className="ai-config-btn" onClick={() => setShowConfig(!showConfig)}>⚙</button>
      </div>

      {showConfig && (
        <div className="ai-config">
          <select value={config.provider} onChange={(e) => {
            const p = e.target.value;
            const bases: Record<string, string> = {
              openai: "https://api.openai.com/v1",
              deepseek: "https://api.deepseek.com",
              ollama: "http://localhost:11434/v1",
              custom: "",
            };
            const models: Record<string, string> = {
              openai: "gpt-4o-mini",
              deepseek: "deepseek-chat",
              ollama: "qwen2.5-coder:7b",
              custom: "",
            };
            setConfig({ ...config, provider: p, apiBase: bases[p] || config.apiBase, model: models[p] || config.model });
          }}>
            <option value="deepseek">DeepSeek</option>
            <option value="openai">OpenAI</option>
            <option value="ollama">Ollama</option>
            <option value="custom">自定义</option>
          </select>
          <input placeholder="API 地址" value={config.apiBase} onChange={(e) => setConfig({ ...config, apiBase: e.target.value })} />
          <input placeholder="API Key" type="password" value={config.apiKey} onChange={(e) => setConfig({ ...config, apiKey: e.target.value })} />
          <input placeholder="模型名称" value={config.model} onChange={(e) => setConfig({ ...config, model: e.target.value })} />
          <button className="ai-save-config" onClick={() => { saveConfig(config); setShowConfig(false); }}>保存</button>
        </div>
      )}

      <div className="ai-messages">
        {messages.length === 0 && (
          <div className="ai-welcome">输入问题，AI 将生成 SQL 查询。</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`ai-msg ai-${m.role}`}>
            <div className="ai-msg-content">{m.content}</div>
            {m.role === "assistant" && (
              <button className="ai-use-sql" onClick={() => onSqlGenerated(extractSql(m.content))}>
                使用 SQL
              </button>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="ai-input-row">
        <textarea
          className="ai-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="问关于数据的问题..."
          rows={2}
        />
        <button className="ai-send-btn" onClick={send} disabled={busy || !config.apiKey}>
          {busy ? "..." : "→"}
        </button>
      </div>
    </div>
  );
}
