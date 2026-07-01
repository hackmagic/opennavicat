"""AI service — natural-language to SQL, optimization, query explanation, schema design, chat."""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("opennavicat.ai")

from open_navicat.models.table_schema import TableInfo


class AIService:
    """AI-powered database assistant — supports multiple LLM backends."""

    def __init__(self) -> None:
        from open_navicat.config import config
        self._provider = config.get("ai.provider") or os.environ.get("OPENNAVICAT_AI_PROVIDER", "openai")
        self._api_key = config.get("ai.api_key") or os.environ.get("OPENNAVICAT_AI_API_KEY", "")
        self._api_base = config.get("ai.api_base") or os.environ.get("OPENNAVICAT_AI_API_BASE", "")
        self._model = config.get("ai.model") or os.environ.get("OPENNAVICAT_AI_MODEL", "gpt-4o-mini")
        self._chat_history: list[dict[str, str]] = []
        self._system_prompt = "You are a helpful database expert assistant."

    def update_config(self, cfg: dict) -> None:
        """Update AI configuration at runtime from a config dict."""
        self._provider = cfg.get("provider", self._provider)
        self._api_key = cfg.get("api_key", self._api_key)
        self._api_base = cfg.get("api_base", self._api_base)
        self._model = cfg.get("model", self._model)

    def test_config(self, cfg: dict | None = None) -> tuple[bool, str]:
        """Test the AI connection with given (or current) config. Returns (ok, message)."""
        if cfg:
            saved = (self._provider, self._api_key, self._api_base, self._model)
            self.update_config(cfg)
        else:
            saved = None

        try:
            msg = self._call_llm([
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with exactly: OK"},
            ], temperature=0.0)
            if "OK" in msg.strip():
                return True, f"提供商: {self._provider}, 模型: {self._model}"
            else:
                return True, f"响应: {msg[:100]}"
        except Exception as e:
            return False, str(e)
        finally:
            if saved:
                self._provider, self._api_key, self._api_base, self._model = saved

    def set_system_prompt(self, prompt: str) -> None:
        self._system_prompt = prompt

    # ---- core LLM call ----

    def _call_llm(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        """Send messages to the configured LLM backend and return the text response."""
        if self._provider == "openai":
            return self._call_openai(messages, temperature)
        elif self._provider == "deepseek":
            return self._call_deepseek(messages, temperature)
        elif self._provider == "ollama":
            return self._call_ollama(messages, temperature)
        elif self._provider == "custom":
            return self._call_custom(messages, temperature)
        else:
            # Default to OpenAI-compatible
            return self._call_openai(messages, temperature)

    def _call_openai(self, messages: list[dict[str, str]], temperature: float) -> str:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key, base_url=self._api_base or None)
            response = client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning("OpenAI API error: %s", e)
            return ""

    def _call_deepseek(self, messages: list[dict[str, str]], temperature: float) -> str:
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=self._api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
                base_url=self._api_base or "https://api.deepseek.com/v1",
            )
            response = client.chat.completions.create(
                model=self._model or "deepseek-chat",
                messages=messages,
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning("DeepSeek API error: %s", e)
            return ""

    def _call_ollama(self, messages: list[dict[str, str]], temperature: float) -> str:
        try:
            import httpx
            base = self._api_base or "http://localhost:11434"
            model = self._model or "llama3"
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            }
            response = httpx.post(
                f"{base}/api/chat",
                json=payload,
                timeout=120,
            )
            data = response.json()
            return data.get("message", {}).get("content", "")
        except Exception as e:
            logger.warning("Ollama error: %s", e)
            return ""

    def _call_custom(self, messages: list[dict[str, str]], temperature: float) -> str:
        """Custom OpenAI-compatible API."""
        try:
            import httpx
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            payload = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
            }
            response = httpx.post(
                self._api_base or "http://localhost:8000/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=120,
            )
            data = response.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            logger.warning("Custom API error: %s", e)
            return ""

    # ---- AI features ----

    def nl2sql(self, description: str, schema_context: str = "") -> str:
        """Convert natural language description to SQL query."""
        prompt = (
            f"Database schema context:\n{schema_context}\n\n"
            f"Convert this natural language request to a SQL query. "
            f"Return ONLY the SQL query, no explanations:\n\n{description}"
        )
        messages = [
            {"role": "system", "content": "You are a SQL expert. Generate clean, correct SQL queries."},
            {"role": "user", "content": prompt},
        ]
        return self._call_llm(messages).strip()

    def optimize(self, sql: str, explain_data: str = "") -> str:
        """Suggest optimizations for a SQL query."""
        context = f"\nEXPLAIN data:\n{explain_data}" if explain_data else ""
        prompt = (
            f"Analyze this SQL query and suggest optimizations:\n\n{sql}{context}\n\n"
            f"Provide: 1) Performance issues found 2) Specific recommendations "
            f"3) Rewritten query if applicable"
        )
        messages = [
            {"role": "system", "content": "You are a SQL performance expert."},
            {"role": "user", "content": prompt},
        ]
        return self._call_llm(messages).strip()

    def explain_query(self, sql: str) -> str:
        """Explain what a SQL query does in plain language."""
        prompt = (
            f"Explain this SQL query in plain language, step by step:\n\n{sql}\n\n"
            f"Describe: 1) What the query does overall 2) Each clause's purpose "
            f"3) Expected result set"
        )
        messages = [
            {"role": "system", "content": "You are a SQL teacher explaining concepts clearly."},
            {"role": "user", "content": prompt},
        ]
        return self._call_llm(messages).strip()

    def fix_sql(self, sql: str, error: str = "") -> str:
        """Fix a broken SQL query."""
        error_context = f"\n\nError message: {error}" if error else ""
        prompt = (
            f"The following SQL query has an error:{error_context}\n\n{sql}\n\n"
            f"Fix the query and return ONLY the corrected SQL."
        )
        messages = [
            {"role": "system", "content": "You are a SQL debugging expert. Fix queries efficiently."},
            {"role": "user", "content": prompt},
        ]
        return self._call_llm(messages).strip()

    def design_schema(self, description: str) -> str:
        """Design a database schema from a natural language description."""
        prompt = (
            f"Design a MySQL database schema based on this requirement:\n\n{description}\n\n"
            f"Requirements:\n"
            f"- Use InnoDB engine\n"
            f"- Include appropriate data types, constraints, primary keys, foreign keys\n"
            f"- Include useful indexes\n"
            f"- Use utf8mb4 charset\n"
            f"- Return complete CREATE TABLE statements with all constraints\n"
            f"- Return ONLY the DDL, no explanations."
        )
        messages = [
            {"role": "system", "content": "You are a database architect. Design clean, normalized schemas."},
            {"role": "user", "content": prompt},
        ]
        return self._call_llm(messages).strip()

    def generate_data(self, table_info: TableInfo, count: int, prompt: str = "") -> list[dict]:
        """Generate realistic test data based on table schema."""
        schema_desc = f"Table: {table_info.name}\n"
        for col in table_info.columns:
            schema_desc += f"  - {col.name} ({col.data_type}), nullable={col.nullable}, default={col.default}\n"
        if prompt:
            schema_desc += f"\nBusiness rules: {prompt}\n"

        json_prompt = (
            f"Generate {count} realistic JSON records for this MySQL table schema:\n\n{schema_desc}\n\n"
            f"Return ONLY a JSON array of objects, no other text. "
            f"Example format: [{{\"col1\": \"value1\", \"col2\": 123}}]"
        )
        messages = [
            {"role": "system", "content": "You are a data generator. Return ONLY valid JSON arrays."},
            {"role": "user", "content": json_prompt},
        ]

        response = self._call_llm(messages, temperature=0.8)
        try:
            # Try to parse JSON from the response
            # Find JSON array in the response
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
                return json.loads(json_str)
            return json.loads(response)
        except (json.JSONDecodeError, ValueError):
            return []

    def ask(self, question: str, schema_context: str = "") -> str:
        """Answer any database-related question."""
        context = f"\n\nDatabase schema:\n{schema_context}" if schema_context else ""
        prompt = f"{question}{context}"
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self._call_llm(messages, temperature=0.3)

    def chat(self, message: str) -> str:
        """Interactive chat with history."""
        self._chat_history.append({"role": "user", "content": message})
        messages = [
            {"role": "system", "content": self._system_prompt},
            *self._chat_history[-20:],  # Keep last 20 turns
        ]
        response = self._call_llm(messages, temperature=0.3)

        self._chat_history.append({"role": "assistant", "content": response})

        # Keep history manageable
        if len(self._chat_history) > 40:
            self._chat_history = self._chat_history[-20:]

        return response


# Module-level singleton
ai_service = AIService()
