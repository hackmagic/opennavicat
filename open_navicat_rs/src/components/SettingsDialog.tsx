import { useState } from "react";

interface Props {
  onClose: () => void;
}

const SETTINGS_KEY = "opennavicat_settings";

interface AppSettings {
  theme: "mocha" | "latte";
  language: "zh" | "en";
  aiProvider: string;
  aiApiBase: string;
  aiApiKey: string;
  aiModel: string;
  editorFontSize: number;
}

function loadSettings(): AppSettings {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null") || defaults;
  } catch { return defaults; }
}

const defaults: AppSettings = {
  theme: "mocha",
  language: "zh",
  aiProvider: "deepseek",
  aiApiBase: "https://api.deepseek.com",
  aiApiKey: "",
  aiModel: "deepseek-chat",
  editorFontSize: 13,
};

export default function SettingsDialog({ onClose }: Props) {
  const [s, setS] = useState<AppSettings>(loadSettings);

  const save = () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
    localStorage.setItem("opennavicat_language", s.language);
    localStorage.setItem("opennavicat_ai_config", JSON.stringify({
      provider: s.aiProvider, apiKey: s.aiApiKey, apiBase: s.aiApiBase, model: s.aiModel,
    }));
    document.documentElement.className = s.theme === "latte" ? "theme-latte" : "";
    onClose();
  };

  const update = <K extends keyof AppSettings>(k: K, v: AppSettings[K]) => setS({ ...s, [k]: v });

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <span>设置</span>
          <button className="settings-close" onClick={onClose}>✕</button>
        </div>
        <div className="settings-body">
          <div className="settings-group">
            <span className="settings-label">主题</span>
            <select value={s.theme} onChange={(e) => update("theme", e.target.value as "mocha" | "latte")}>
              <option value="mocha">Catppuccin Mocha (暗色)</option>
              <option value="latte">Catppuccin Latte (亮色)</option>
            </select>
          </div>

          <div className="settings-group">
            <span className="settings-label">语言 / Language</span>
            <select value={s.language} onChange={(e) => update("language", e.target.value as "zh" | "en")}>
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>

          <div className="settings-group">
            <span className="settings-label">AI 提供商</span>
            <select value={s.aiProvider} onChange={(e) => update("aiProvider", e.target.value)}>
              <option value="deepseek">DeepSeek</option>
              <option value="openai">OpenAI</option>
              <option value="ollama">Ollama (本地)</option>
              <option value="custom">自定义</option>
            </select>
          </div>

          <div className="settings-group">
            <span className="settings-label">API 地址</span>
            <input value={s.aiApiBase} onChange={(e) => update("aiApiBase", e.target.value)} placeholder="https://api.deepseek.com" />
          </div>

          <div className="settings-group">
            <span className="settings-label">API Key</span>
            <input type="password" value={s.aiApiKey} onChange={(e) => update("aiApiKey", e.target.value)} placeholder="sk-..." />
          </div>

          <div className="settings-group">
            <span className="settings-label">模型</span>
            <input value={s.aiModel} onChange={(e) => update("aiModel", e.target.value)} placeholder="deepseek-chat" />
          </div>

          <div className="settings-group">
            <span className="settings-label">编辑器字号</span>
            <input type="number" min={10} max={24} value={s.editorFontSize} onChange={(e) => update("editorFontSize", Number(e.target.value))} />
          </div>

          <button className="designer-btn primary" onClick={save} style={{ alignSelf: "flex-end" }}>保存设置</button>
        </div>
      </div>
    </div>
  );
}
