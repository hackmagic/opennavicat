"""AI service — natural-language to SQL, optimization, query explanation, schema design, chat, agent."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("opennavicat.ai")

from open_navicat.models.table_schema import TableInfo


class AIError(Exception):
    """Raised on non-transient AI API errors (auth, model not found, etc)."""


class AITransientError(Exception):
    """Raised on transient failures that may succeed on retry (timeout, rate limit)."""


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
        self._schema_embeddings: dict[str, str] = {}
        self._schema_embedding_conn: tuple[str, str] | None = None  # (connection_id, database) cache key

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
            msg = self._call_llm_text([
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

    # ── Function definition templates ──────────────────────────────────

    def _agent_tools(self) -> list[dict]:
        """Return tool definitions for the AI agent."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_schema",
                    "description": "Get the schema (columns, types, indexes) of a table",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table": {"type": "string", "description": "Table name"}
                        },
                        "required": ["table"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_tables",
                    "description": "List all tables in the current database",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_sql",
                    "description": "Execute a SQL query and return results",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "SQL query to execute"},
                        },
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_ai",
                    "description": "Ask a general database knowledge question (syntax, best practices, etc.)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "Question about databases or SQL"},
                        },
                        "required": ["question"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_report",
                    "description": "Generate a natural-language report from query results",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "data": {"type": "string", "description": "Query results as JSON or formatted text"},
                            "question": {"type": "string", "description": "The original question the data answers"},
                        },
                        "required": ["data", "question"],
                    },
                },
            },
        ]

    # ---- core LLM call ----

    def _call_llm_text(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        """Convenience: call LLM and return only text content."""
        text, _ = self._call_llm(messages, temperature)
        return text

    def _call_llm(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict] | None]:
        """Send messages to the configured LLM backend with retry.

        Returns (text_content, tool_calls) where tool_calls is a list of
        {"name": ..., "arguments": {...}} dicts, or None if no tools were used.
        """
        import time

        provider_dispatch = {
            "openai": self._call_openai,
            "deepseek": self._call_deepseek,
            "ollama": self._call_ollama,
            "custom": self._call_custom,
        }
        caller = provider_dispatch.get(self._provider, self._call_openai)

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return caller(messages, temperature, tools)
            except AITransientError as e:
                last_error = e
                if attempt < 2:
                    delay = 1.5 ** attempt
                    logger.warning("Transient AI error (attempt %d/3): %s — retrying in %.1fs", attempt + 1, e, delay)
                    time.sleep(delay)
                else:
                    logger.error("AI call failed after 3 attempts: %s", e)
            except AIError as e:
                raise e

        raise AIError(f"AI provider unavailable after 3 retries: {last_error}")

    def _call_openai(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict] | None]:
        try:
            from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
            client = OpenAI(api_key=self._api_key, base_url=self._api_base or None)
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
            }
            if tools:
                kwargs["tools"] = tools
            response = client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            text = msg.content or ""
            tool_calls = None
            if msg.tool_calls:
                tool_calls = [
                    {"name": tc.function.name, "arguments": json.loads(tc.function.arguments)}
                    for tc in msg.tool_calls
                ]
            return text, tool_calls
        except RateLimitError as e:
            raise AITransientError(f"Rate limited: {e}") from e
        except APITimeoutError as e:
            raise AITransientError(f"Request timed out: {e}") from e
        except APIConnectionError as e:
            raise AITransientError(f"Connection failed: {e}") from e
        except APIError as e:
            if e.status_code and 500 <= e.status_code < 600:
                raise AITransientError(f"Server error ({e.status_code}): {e}") from e
            raise AIError(f"API error ({e.status_code}): {e}") from e
        except Exception as e:
            logger.error("Unexpected OpenAI error: %s", e, exc_info=True)
            raise AIError(str(e)) from e

    def _call_deepseek(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict] | None]:
        try:
            from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
            client = OpenAI(
                api_key=self._api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
                base_url=self._api_base or "https://api.deepseek.com/v1",
            )
            kwargs: dict[str, Any] = {
                "model": self._model or "deepseek-chat",
                "messages": messages,
                "temperature": temperature,
            }
            if tools:
                kwargs["tools"] = tools
            response = client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            text = msg.content or ""
            tool_calls = None
            if msg.tool_calls:
                tool_calls = [
                    {"name": tc.function.name, "arguments": json.loads(tc.function.arguments)}
                    for tc in msg.tool_calls
                ]
            return text, tool_calls
        except RateLimitError as e:
            raise AITransientError(f"DeepSeek rate limited: {e}") from e
        except APITimeoutError as e:
            raise AITransientError(f"DeepSeek request timed out: {e}") from e
        except APIConnectionError as e:
            raise AITransientError(f"DeepSeek connection failed: {e}") from e
        except APIError as e:
            if e.status_code and 500 <= e.status_code < 600:
                raise AITransientError(f"DeepSeek server error ({e.status_code})") from e
            raise AIError(f"DeepSeek API error ({e.status_code}): {e}") from e
        except Exception as e:
            logger.error("Unexpected DeepSeek error: %s", e, exc_info=True)
            raise AIError(str(e)) from e

    def _call_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict] | None]:
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
            if tools:
                payload["tools"] = tools
            response = httpx.post(
                f"{base}/api/chat",
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            msg = data.get("message", {})
            text = msg.get("content", "")
            tool_calls = None
            raw_tools = msg.get("tool_calls")
            if raw_tools:
                tool_calls = []
                for tc in raw_tools:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tool_calls.append({"name": fn.get("name", ""), "arguments": args})
            return text, tool_calls
        except httpx.TimeoutException as e:
            raise AITransientError(f"Ollama request timed out: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise AITransientError("Ollama rate limited") from e
            raise AIError(f"Ollama error ({e.response.status_code}): {e.response.text[:200]}") from e
        except httpx.ConnectError as e:
            raise AITransientError(f"Ollama connection refused (is ollama running?): {e}") from e
        except Exception as e:
            logger.error("Unexpected Ollama error: %s", e, exc_info=True)
            raise AIError(str(e)) from e

    def _call_custom(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        tools: list[dict] | None = None,
    ) -> tuple[str, list[dict] | None]:
        """Custom OpenAI-compatible API."""
        try:
            import httpx
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
            }
            if tools:
                payload["tools"] = tools
            response = httpx.post(
                self._api_base or "http://localhost:8000/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            msg = data.get("choices", [{}])[0].get("message", {})
            text = msg.get("content", "")
            tool_calls = None
            raw_tools = msg.get("tool_calls")
            if raw_tools:
                tool_calls = []
                for tc in raw_tools:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tool_calls.append({"name": fn.get("name", ""), "arguments": args})
            return text, tool_calls
        except httpx.TimeoutException as e:
            raise AITransientError(f"Custom API request timed out: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise AITransientError("Custom API rate limited") from e
            raise AIError(f"Custom API error ({e.response.status_code}): {e.response.text[:200]}") from e
        except httpx.ConnectError as e:
            raise AITransientError(f"Custom API connection refused: {e}") from e
        except Exception as e:
            logger.error("Unexpected Custom API error: %s", e, exc_info=True)
            raise AIError(str(e)) from e

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
        return self._call_llm_text(messages).strip()

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
        return self._call_llm_text(messages).strip()

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
        return self._call_llm_text(messages).strip()

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
        return self._call_llm_text(messages).strip()

    def data_quality(self, table_name: str, schema_context: str, sample_data: str = "") -> str:
        """Analyze data quality issues in a table."""
        prompt = f"Analyze data quality issues for table `{table_name}`.\nSchema:\n{schema_context}\n"
        if sample_data:
            prompt += f"Sample data:\n{sample_data}\n"
        prompt += "\nCheck for: NULL rates, duplicate values, format issues, outliers. Give specific findings."
        messages = [{"role": "system", "content": "You are a data quality analyst."},
                    {"role": "user", "content": prompt}]
        return self._call_llm_text(messages)

    def anomaly_detection(self, table_name: str, column: str, sql_sampling: str = "") -> str:
        """Detect anomalies in table data."""
        prompt = f"Suggest SQL queries to detect anomalies in table `{table_name}`, column `{column}`."
        if sql_sampling:
            prompt += f"\nAvailable via SQL:\n{sql_sampling}"
        messages = [{"role": "system", "content": "You are an anomaly detection expert."},
                    {"role": "user", "content": prompt}]
        return self._call_llm_text(messages)

    def sql_review(self, sql: str, schema_context: str = "") -> str:
        """Review SQL for security and performance issues."""
        prompt = f"Review this SQL query for security and performance issues:\n```sql\n{sql}\n```\n"
        if schema_context:
            prompt += f"\nSchema context:\n{schema_context}\n"
        prompt += "\nCheck: SQL injection risks, missing WHERE on DELETE/UPDATE, N+1 queries, missing indexes, SELECT * in production."
        messages = [{"role": "system", "content": "You are a SQL security and performance reviewer."},
                    {"role": "user", "content": prompt}]
        return self._call_llm_text(messages)

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
        return self._call_llm_text(messages).strip()

    def design_schema_iterative(self, current_ddl: str, request: str) -> str:
        """Iteratively modify an existing schema based on a natural language request.

        Args:
            current_ddl: The current CREATE TABLE statement(s).
            request: A natural language modification request (e.g. "add an index on email").

        Returns:
            Updated DDL with the requested modifications applied.
        """
        prompt = (
            f"Current schema:\n{current_ddl}\n\n"
            f"Modification request: {request}\n\n"
            f"Apply the requested change and return the COMPLETE updated CREATE TABLE statement(s). "
            f"Also include ALTER TABLE statements needed to migrate from the old schema. "
            f"Return ONLY the SQL, no explanations."
        )
        messages = [
            {"role": "system", "content": "You are a database migration expert."},
            {"role": "user", "content": prompt},
        ]
        return self._call_llm_text(messages).strip()

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

        response = self._call_llm_text(messages, temperature=0.8)
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
        return self._call_llm_text(messages, temperature=0.3)

    def chat(self, message: str) -> str:
        """Interactive chat with history."""
        self._chat_history.append({"role": "user", "content": message})
        messages = [
            {"role": "system", "content": self._system_prompt},
            *self._chat_history[-20:],  # Keep last 20 turns
        ]
        response = self._call_llm_text(messages, temperature=0.3)

        self._chat_history.append({"role": "assistant", "content": response})

        # Keep history manageable
        if len(self._chat_history) > 40:
            self._chat_history = self._chat_history[-20:]

        return response

    # ---- Schema RAG ----

    def build_schema_context(
        self,
        connection_id: str,
        database: str,
        tables: list[str] | None = None,
        max_tables: int = 10,
    ) -> str:
        """Build schema context string for RAG-enhanced prompts.

        Fetches column/index/FK info for the specified tables (or all tables
        in the database if not specified) and formats it as concise text.
        """
        from open_navicat.services.metadata_service import metadata_service

        if tables is None:
            from open_navicat.dal.connection_pool import connection_pool
            conn = connection_pool.get(connection_id)
            if not conn:
                return ""
            from open_navicat.dal.connection_pool import _loop
            # Use the target database
            table_names = _loop.run_until_complete(conn.list_tables(database))
            tables = [t.name for t in table_names][:max_tables]

        parts: list[str] = []
        for tbl in tables[:max_tables]:
            info = metadata_service.get_table_info(connection_id, database, tbl)
            if not info:
                continue
            lines = [f"CREATE TABLE {tbl} ("]
            for col in info.columns:
                parts_col = [f"  {col.name} {col.data_type}"]
                if not col.nullable:
                    parts_col.append("NOT NULL")
                if col.is_primary_key:
                    parts_col.append("PRIMARY KEY")
                if col.default:
                    parts_col.append(f"DEFAULT {col.default}")
                lines.append(" ".join(parts_col) + ",")
            # Indexes
            for idx in info.indexes:
                cols = ", ".join(idx.columns)
                if idx.is_primary:
                    lines.append(f"  PRIMARY KEY ({cols}),")
                elif idx.is_unique:
                    lines.append(f"  UNIQUE KEY {idx.name} ({cols}),")
                else:
                    lines.append(f"  INDEX {idx.name} ({cols}),")
            # FKs
            for fk in info.foreign_keys:
                lines.append(
                    f"  FOREIGN KEY ({fk.column}) REFERENCES "
                    f"{fk.ref_table}({fk.ref_column}),"
                )
            # Remove trailing comma from last line
            if lines[-1].endswith(","):
                lines[-1] = lines[-1][:-1]
            lines.append(");")
            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    def build_schema_context_for_query(
        self, connection_id: str, database: str, query: str, top_k: int = 5
    ) -> str:
        """Build schema context for only the tables relevant to a natural language query.

        Uses keyword matching first; if scores are low, falls back to LLM table selection.
        """
        self._ensure_embeddings(connection_id, database)
        keyword_tables = self._keyword_search_tables(query, top_k)

        if keyword_tables and keyword_tables[0][0] >= 2:
            table_names = [t for _, t in keyword_tables[:top_k]]
        else:
            table_names = self._llm_select_tables(query, list(self._schema_embeddings.keys()))

        return self.build_schema_context(connection_id, database, table_names, max_tables=top_k)

    def _ensure_embeddings(self, connection_id: str, database: str) -> None:
        """Build embeddings if not cached for this connection+database."""
        cache_key = (connection_id, database)
        if self._schema_embedding_conn == cache_key and self._schema_embeddings:
            return
        from open_navicat.services.metadata_service import metadata_service
        tables = metadata_service.list_tables(connection_id, database)
        self._schema_embeddings = {}
        for t in tables:
            info = metadata_service.get_table_info(connection_id, database, t)
            if info:
                text = f"Table {t}: " + ", ".join(f"{c.name} ({c.data_type})" for c in info.columns)
                self._schema_embeddings[t] = text
        self._schema_embedding_conn = cache_key

    def _keyword_search_tables(self, query: str, top_k: int = 5) -> list[tuple[int, str]]:
        """Score tables by keyword overlap with the query."""
        if not self._schema_embeddings:
            return []
        query_words = set(query.lower().split())
        scored: list[tuple[int, str]] = []
        for name, text in self._schema_embeddings.items():
            score = sum(1 for w in query_words if w in text.lower())
            if score > 0:
                scored.append((score, name))
        scored.sort(reverse=True)
        return scored[:top_k]

    def _llm_select_tables(self, query: str, all_tables: list[str]) -> list[str]:
        """Ask LLM which tables are relevant to the query."""
        prompt = (
            f"A user asked about a database: '{query}'\n\n"
            f"Available tables: {', '.join(all_tables)}\n\n"
            "Return ONLY a comma-separated list of the most relevant table names (max 5), nothing else."
        )
        reply = self._call_llm_text([
            {"role": "system", "content": "You are a database expert. Select relevant tables."},
            {"role": "user", "content": prompt},
        ], temperature=0.0).strip()
        return [t.strip() for t in reply.split(",") if t.strip() in all_tables][:5]

    def nl2sql_with_rag(self, description: str, connection_id: str, database: str) -> str:
        """Natural language to SQL with schema RAG context."""
        schema = self.build_schema_context_for_query(connection_id, database, description)
        return self.nl2sql(description, schema_context=schema)

    def ask_with_rag(self, question: str, connection_id: str, database: str) -> str:
        """Answer a database question with schema RAG context."""
        schema = self.build_schema_context_for_query(connection_id, database, question)
        return self.ask(question, schema_context=schema)

    # ---- Schema Embeddings (lightweight RAG) ----

    def build_schema_embeddings(self, connection_id: str, database: str) -> None:
        """Build in-memory text embeddings for schema tables (public API)."""
        self._ensure_embeddings(connection_id, database)

    def semantic_search_schema(self, query: str, top_k: int = 3) -> str:
        """Keyword-based search: find tables relevant to a query."""
        scored = self._keyword_search_tables(query, top_k)
        if not scored:
            return ""
        return "\n".join(self._schema_embeddings.get(t) for _, t in scored if t in self._schema_embeddings)

    # ---- ReAct Agent ----

    @dataclass
    class AgentStep:
        """One step in the agent's reasoning loop."""
        thought: str = ""
        action: str = ""
        action_input: str = ""
        observation: str = ""

    @dataclass
    class AgentResult:
        """Final result from the agent."""
        answer: str = ""
        steps: list["AIService.AgentStep"] = field(default_factory=list)
        sql: str = ""

    def _needs_confirmation(self, sql: str) -> bool:
        """Check if SQL requires user confirmation before execution."""
        from open_navicat.utils.sql_formatter import classify_sql
        return classify_sql(sql) in ("ddl", "dml")

    def agent(
        self,
        request: str,
        connection_id: str = "",
        database: str = "",
        max_steps: int = 5,
        confirm_callback: callable | None = None,
    ) -> AgentResult:
        """Function Calling agent that reasons, calls tools, and answers.

        Uses native tool/function calling via the LLM API (OpenAI-compatible).
        Falls back to text-based ReAct if the response doesn't contain tool_calls.
        """
        from open_navicat.services.metadata_service import metadata_service
        from open_navicat.services.query_engine import query_engine

        result = self.AgentResult()
        context_parts: list[str] = []

        if connection_id and database:
            schema_ctx = self.build_schema_context(connection_id, database)
            if schema_ctx:
                context_parts.append(f"Available schema:\n{schema_ctx}")

        system = (
            "You are a database assistant. You have access to tools to explore "
            "the database schema, execute SQL queries, ask database knowledge questions, "
            "and generate reports from data. Use them step by step. "
            "When you have the answer, respond directly to the user."
        )

        history: list[dict[str, str]] = [
            {"role": "system", "content": system},
        ]

        user_msg = f"Request: {request}"
        if context_parts:
            user_msg += "\n\n" + "\n\n".join(context_parts)
        history.append({"role": "user", "content": user_msg})

        tools = self._agent_tools()

        for step_i in range(max_steps):
            text, tool_calls = self._call_llm(history, temperature=0.1, tools=tools)
            step = self.AgentStep()

            if not text and not tool_calls:
                break

            # Handle text response (could be final answer or text-based ReAct fallback)
            if text:
                history.append({"role": "assistant", "content": text})
                # Check if it looks like a final answer (no action JSON)
                if not tool_calls and not text.strip().startswith("{"):
                    result.answer = text
                    step.action = "answer"
                    step.observation = text
                    result.steps.append(step)
                    break

            # Handle tool calls
            if tool_calls:
                for tc in tool_calls:
                    fn_name = tc.get("name", "")
                    fn_args = tc.get("arguments", {})
                    step = self.AgentStep()
                    step.action = fn_name
                    step.action_input = json.dumps(fn_args, ensure_ascii=False)

                    if fn_name == "search_schema":
                        tbl = fn_args.get("table", "")
                        if connection_id and database and tbl:
                            info = metadata_service.get_table_info(connection_id, database, tbl)
                            if info:
                                cols = ", ".join(f"{c.name} ({c.data_type})" for c in info.columns)
                                step.observation = f"Table {tbl}: columns=[{cols}]"
                            else:
                                step.observation = f"Table '{tbl}' not found"
                        else:
                            step.observation = "No connection or table name provided"

                    elif fn_name == "list_tables":
                        if connection_id and database:
                            from open_navicat.dal.connection_pool import _loop, connection_pool
                            conn = connection_pool.get(connection_id)
                            if conn:
                                tables = _loop.run_until_complete(conn.list_tables(database))
                                names = [t.name for t in tables]
                                step.observation = f"Tables: {', '.join(names)}"
                            else:
                                step.observation = "No connection available"
                        else:
                            step.observation = "No connection or database specified"

                    elif fn_name == "execute_sql":
                        sql = fn_args.get("sql", "")
                        if connection_id:
                            if self._needs_confirmation(sql):
                                confirmed = True
                                if confirm_callback:
                                    confirmed = confirm_callback(sql)
                                if not confirmed:
                                    step.observation = "Execution cancelled by user"
                                    history.append({
                                        "role": "tool",
                                        "content": step.observation,
                                    })
                                    result.steps.append(step)
                                    continue
                            try:
                                qr = query_engine.execute(connection_id, sql)
                                if qr.rows:
                                    from open_navicat.utils.data_masker import mask_row
                                    col_names = [c.name for c in (qr.columns or [])]
                                    masked = [mask_row(r, col_names) for r in qr.rows[:10]]
                                    rows_str = json.dumps(masked, default=str, ensure_ascii=False)
                                    step.observation = f"Result ({len(qr.rows)} rows): {rows_str}"
                                else:
                                    step.observation = f"Query OK, {qr.row_count} rows affected"
                                result.sql = sql
                            except Exception as e:
                                step.observation = f"Error: {e}"
                        else:
                            step.observation = "No active connection"

                    elif fn_name == "ask_ai":
                        question = fn_args.get("question", "")
                        step.observation = self.ask(question)

                    elif fn_name == "generate_report":
                        data = fn_args.get("data", "")
                        question = fn_args.get("question", "")
                        prompt = (
                            f"Based on this question: {question}\n\n"
                            f"And the following query results:\n{data}\n\n"
                            "Generate a concise natural-language report that answers "
                            "the question. Include key numbers and findings."
                        )
                        step.observation = self._call_llm_text([
                            {"role": "system", "content": "You are a data analyst. Generate clear reports from data."},
                            {"role": "user", "content": prompt},
                        ], temperature=0.1)

                    else:
                        step.observation = f"Unknown function: {fn_name}"

                    result.steps.append(step)
                    history.append({
                        "role": "tool",
                        "content": step.observation,
                    })

            # No tool_calls and no text → done
            if not tool_calls and text:
                break

        if not result.answer and result.steps:
            result.answer = result.steps[-1].observation

        return result

    # ---- Chat history persistence ----

    def save_chat_history(self, session_id: str = "default") -> None:
        """Persist chat history to local SQLite config."""
        from open_navicat.dal.local_config import local_db
        local_db.set_setting(f"ai_chat_history_{session_id}", self._chat_history)

    def load_chat_history(self, session_id: str = "default") -> None:
        """Load chat history from local SQLite config."""
        from open_navicat.dal.local_config import local_db
        history = local_db.get_setting(f"ai_chat_history_{session_id}", [])
        if history:
            self._chat_history = history

    def clear_chat_history(self, session_id: str = "default") -> None:
        """Clear persisted chat history."""
        from open_navicat.dal.local_config import local_db
        self._chat_history = []
        local_db.set_setting(f"ai_chat_history_{session_id}", [])


# Module-level singleton
ai_service = AIService()
