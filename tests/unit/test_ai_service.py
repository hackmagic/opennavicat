"""Tests for AI service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from open_navicat.services.ai_service import AIError


@pytest.fixture
def ai_service():
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key: {
        "ai.provider": "openai",
        "ai.api_key": "test-key",
        "ai.api_base": "",
        "ai.model": "test-model",
    }.get(key, "")
    with patch("open_navicat.config.config", mock_config):
        from open_navicat.services.ai_service import AIService
        svc = AIService()
        return svc


class TestAIService:
    def test_init_defaults(self, ai_service):
        assert ai_service._provider == "openai"
        assert ai_service._api_key == "test-key"
        assert ai_service._model == "test-model"

    def test_update_config(self, ai_service):
        ai_service.update_config({"provider": "ollama", "model": "llama3"})
        assert ai_service._provider == "ollama"
        assert ai_service._model == "llama3"

    def test_set_system_prompt(self, ai_service):
        ai_service.set_system_prompt("Custom prompt")
        assert ai_service._system_prompt == "Custom prompt"

    def test_call_llm_routes_to_openai(self, ai_service):
        with patch.object(ai_service, "_call_openai", return_value=("OK", None)) as mock:
            text, tools = ai_service._call_llm([{"role": "user", "content": "hi"}])
            mock.assert_called_once()
            assert text == "OK"
            assert tools is None

    def test_call_llm_routes_to_ollama(self, ai_service):
        ai_service._provider = "ollama"
        with patch.object(ai_service, "_call_ollama", return_value=("OK", None)) as mock:
            ai_service._call_llm([{"role": "user", "content": "hi"}])
            mock.assert_called_once()

    def test_call_llm_routes_to_deepseek(self, ai_service):
        ai_service._provider = "deepseek"
        with patch.object(ai_service, "_call_deepseek", return_value=("OK", None)) as mock:
            ai_service._call_llm([{"role": "user", "content": "hi"}])
            mock.assert_called_once()

    def test_call_llm_routes_to_custom(self, ai_service):
        ai_service._provider = "custom"
        with patch.object(ai_service, "_call_custom", return_value=("OK", None)) as mock:
            ai_service._call_llm([{"role": "user", "content": "hi"}])
            mock.assert_called_once()

    def test_call_openai_success(self, ai_service):
        mock_response = MagicMock()
        msg = MagicMock(content="Hello")
        msg.tool_calls = None
        mock_response.choices = [MagicMock(message=msg)]
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = mock_response
            text, tools = ai_service._call_openai([{"role": "user", "content": "hi"}], 0.1)
            assert text == "Hello"
            assert tools is None

    def test_call_openai_error_raises(self, ai_service):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.side_effect = Exception("API error")
            with pytest.raises(AIError, match="API error"):
                ai_service._call_openai([{"role": "user", "content": "hi"}], 0.1)

    def test_nl2sql(self, ai_service):
        with patch.object(ai_service, "_call_llm_text", return_value="SELECT * FROM users"):
            result = ai_service.nl2sql("show all users", "users(id, name)")
            assert "SELECT" in result

    def test_optimize(self, ai_service):
        with patch.object(ai_service, "_call_llm_text", return_value="Use index on column"):
            result = ai_service.optimize("SELECT * FROM t WHERE x=1")
            assert "index" in result.lower() or "use" in result.lower()

    def test_explain_query(self, ai_service):
        with patch.object(ai_service, "_call_llm_text", return_value="This query selects all rows"):
            result = ai_service.explain_query("SELECT * FROM t")
            assert "select" in result.lower()

    def test_fix_sql(self, ai_service):
        with patch.object(ai_service, "_call_llm_text", return_value="SELECT * FROM t"):
            result = ai_service.fix_sql("SELCT * FORM t")
            assert result

    def test_generate_data_returns_list(self, ai_service):
        from open_navicat.models.table_schema import ColumnInfo, TableInfo
        table_info = TableInfo(name="users", database="testdb")
        table_info.columns = [ColumnInfo(name="id", data_type="INT"), ColumnInfo(name="name", data_type="VARCHAR")]
        with patch.object(ai_service, "_call_llm_text", return_value='[{"id": 1, "name": "test"}]'):
            result = ai_service.generate_data(table_info, 1)
            assert isinstance(result, list)
            assert len(result) == 1

    def test_generate_data_invalid_json_returns_empty(self, ai_service):
        from open_navicat.models.table_schema import ColumnInfo, TableInfo
        table_info = TableInfo(name="users", database="testdb")
        table_info.columns = [ColumnInfo(name="id", data_type="INT")]
        with patch.object(ai_service, "_call_llm_text", return_value="not json"):
            result = ai_service.generate_data(table_info, 1)
            assert result == []

    def test_chat_appends_history(self, ai_service):
        with patch.object(ai_service, "_call_llm_text", return_value="Hi there"):
            result = ai_service.chat("Hello")
            assert result == "Hi there"
            assert len(ai_service._chat_history) == 2

    def test_call_llm_text_wrapper(self, ai_service):
        """Test that _call_llm_text extracts text from the tuple return."""
        with patch.object(ai_service, "_call_llm", return_value=("Hello", None)):
            result = ai_service._call_llm_text([{"role": "user", "content": "hi"}])
            assert result == "Hello"

    def test_agent_returns_result(self, ai_service):
        """Agent returns AgentResult even without tools available."""
        with patch.object(ai_service, "_call_llm", return_value=("Tables: users, orders", None)):
            result = ai_service.agent("list tables", connection_id="c1", database="db1")
            assert result.answer is not None

    def test_agent_handles_tool_calls(self, ai_service):
        """Agent processes tool calls from LLM response."""
        tool_calls = [{"name": "list_tables", "arguments": {}}]
        with patch.object(ai_service, "_call_llm", return_value=("", tool_calls)):
            with patch.object(ai_service, "build_schema_context", return_value="test schema"):
                result = ai_service.agent("list tables", connection_id="c1", database="db1", max_steps=1)
                assert len(result.steps) > 0

    def test_agent_fallback_on_empty(self, ai_service):
        """Agent handles empty response gracefully."""
        with patch.object(ai_service, "_call_llm", return_value=("", None)):
            result = ai_service.agent("test", max_steps=1)
            assert result is not None

    # ---- Schema RAG tests ----

    def test_ensure_embeddings_builds_once(self, ai_service):
        """Embddings are cached per connection+database."""
        target = "open_navicat.services.metadata_service.metadata_service"
        with patch(target) as mock_meta:
            mock_meta.list_tables.return_value = ["users", "orders"]
            col = MagicMock(name="id", data_type="INT")
            mock_meta.get_table_info.return_value = MagicMock(columns=[col], indexes=[], foreign_keys=[])
            ai_service._ensure_embeddings("c1", "db1")
            assert len(ai_service._schema_embeddings) == 2
            assert mock_meta.list_tables.call_count == 1

            mock_meta.reset_mock()
            ai_service._ensure_embeddings("c1", "db1")
            mock_meta.list_tables.assert_not_called()

    def test_ensure_embeddings_switches_conn(self, ai_service):
        """Cached embeddings are rebuilt when connection changes."""
        target = "open_navicat.services.metadata_service.metadata_service"
        with patch(target) as mock_meta:
            mock_meta.list_tables.return_value = ["products"]
            col = MagicMock(name="name", data_type="TEXT")
            mock_meta.get_table_info.return_value = MagicMock(columns=[col], indexes=[], foreign_keys=[])
            ai_service._ensure_embeddings("c1", "db1")
            ai_service._ensure_embeddings("c2", "db2")
            assert mock_meta.list_tables.call_count == 2

    def test_keyword_search_tables(self, ai_service):
        """Keyword search finds relevant tables."""
        ai_service._schema_embeddings = {
            "users": "Table users: id (INT), name (VARCHAR), email (VARCHAR)",
            "products": "Table products: id (INT), title (VARCHAR), price (DECIMAL)",
            "orders": "Table orders: id (INT), user_id (INT), total (DECIMAL)",
        }
        scored = ai_service._keyword_search_tables("find users by email", top_k=3)
        assert len(scored) > 0
        top_name = scored[0][1]
        assert top_name == "users"

    def test_keyword_search_no_match(self, ai_service):
        """Empty results when nothing matches."""
        ai_service._schema_embeddings = {}
        scored = ai_service._keyword_search_tables("anything", top_k=3)
        assert scored == []

    def test_semantic_search_schema_public_api(self, ai_service):
        """Public semantic_search_schema returns correct format."""
        ai_service._schema_embeddings = {
            "users": "Table users: id (INT), name (VARCHAR)",
        }
        result = ai_service.semantic_search_schema("users")
        assert "Table users" in result

    def test_build_schema_context_for_query_keyword(self, ai_service):
        """Uses keyword path when score >= 2."""
        ai_service._schema_embeddings = {
            "users": "Table users: id (INT), name (VARCHAR), email (VARCHAR)",
            "orders": "Table orders: id (INT), user_id (INT), total (DECIMAL)",
        }
        ai_service._schema_embedding_conn = ("c1", "db1")
        with patch.object(ai_service, "build_schema_context", return_value="context for users") as mock:
            result = ai_service.build_schema_context_for_query("c1", "db1", "find users by email")
            mock.assert_called_once()
            assert result == "context for users"

    def test_build_schema_context_for_query_llm_fallback(self, ai_service):
        """Uses LLM path when keyword scores are low."""
        ai_service._schema_embeddings = {
            "users": "Table users: id (INT), name (VARCHAR)",
            "products": "Table products: id (INT), title (VARCHAR)",
        }
        ai_service._schema_embedding_conn = ("c1", "db1")
        with patch.object(ai_service, "_llm_select_tables", return_value=["users"]) as mock_llm:
            with patch.object(ai_service, "build_schema_context", return_value="context from llm"):
                result = ai_service.build_schema_context_for_query("c1", "db1", "xyzzy")
                mock_llm.assert_called_once()
                assert result == "context from llm"

    def test_llm_select_tables(self, ai_service):
        """_llm_select_tables calls LLM and parses response."""
        with patch.object(ai_service, "_call_llm_text", return_value="users, orders"):
            result = ai_service._llm_select_tables("show users", ["users", "orders", "products"])
            assert result == ["users", "orders"]

    def test_llm_select_tables_ignores_unknown(self, ai_service):
        """Response containing non-existent table names are filtered out."""
        with patch.object(ai_service, "_call_llm_text", return_value="users, nonexistent"):
            result = ai_service._llm_select_tables("show users", ["users"])
            assert result == ["users"]

    def test_llm_select_tables_empty_reply(self, ai_service):
        """Fallback on empty LLM reply."""
        with patch.object(ai_service, "_call_llm_text", return_value=""):
            result = ai_service._llm_select_tables("test", ["users"])
            assert result == []

    def test_nl2sql_with_rag(self, ai_service):
        """nl2sql_with_rag delegates to build_schema_context_for_query."""
        with patch.object(ai_service, "build_schema_context_for_query", return_value="schema"):
            with patch.object(ai_service, "nl2sql", return_value="SELECT * FROM users"):
                result = ai_service.nl2sql_with_rag("show users", "c1", "db1")
                assert "SELECT" in result

    def test_ask_with_rag(self, ai_service):
        """ask_with_rag delegates to build_schema_context_for_query."""
        with patch.object(ai_service, "build_schema_context_for_query", return_value="schema"):
            with patch.object(ai_service, "ask", return_value="42 rows"):
                result = ai_service.ask_with_rag("how many users?", "c1", "db1")
                assert "42" in result

    def test_needs_confirmation_select(self, ai_service):
        """SELECT doesn't need confirmation."""
        assert ai_service._needs_confirmation("SELECT * FROM users") is False

    def test_needs_confirmation_ddl(self, ai_service):
        """DDL needs confirmation."""
        assert ai_service._needs_confirmation("DROP TABLE users") is True

    def test_needs_confirmation_dml(self, ai_service):
        """DML needs confirmation."""
        assert ai_service._needs_confirmation("DELETE FROM users") is True

    def test_agent_confirm_callback_cancels_ddl(self, ai_service):
        """Agent skips execution when confirm_callback returns False."""
        from unittest.mock import MagicMock
        callback = MagicMock(return_value=False)
        tool_calls = [{"name": "execute_sql", "arguments": {"sql": "DROP TABLE users"}}]
        with patch.object(ai_service, "_call_llm", return_value=("", tool_calls)):
            result = ai_service.agent("drop table", connection_id="c1", database="db1",
                                      max_steps=1, confirm_callback=callback)
            callback.assert_called_once_with("DROP TABLE users")
            assert any("cancelled" in s.observation for s in result.steps)

    def test_agent_confirm_callback_allows(self, ai_service):
        """Agent executes when confirm_callback returns True."""
        callback = MagicMock(return_value=True)
        tool_calls = [{"name": "execute_sql", "arguments": {"sql": "DELETE FROM orders"}}]
        target = "open_navicat.services.query_engine.query_engine"
        with patch.object(ai_service, "_call_llm", return_value=("", tool_calls)):
            with patch(target) as mock_qe:
                mock_qe.execute.return_value = MagicMock(rows=None, row_count=5)
                ai_service.agent("delete orders", connection_id="c1", database="db1",
                                 max_steps=1, confirm_callback=callback)
                callback.assert_called_once()
                mock_qe.execute.assert_called_once_with("c1", "DELETE FROM orders")

    def test_agent_no_confirm_for_select(self, ai_service):
        """SELECT doesn't trigger confirm_callback."""
        callback = MagicMock()
        tool_calls = [{"name": "execute_sql", "arguments": {"sql": "SELECT * FROM users"}}]
        target = "open_navicat.services.query_engine.query_engine"
        with patch.object(ai_service, "_call_llm", return_value=("", tool_calls)):
            with patch(target) as mock_qe:
                mock_qe.execute.return_value = MagicMock(rows=[], row_count=0)
                ai_service.agent("select", connection_id="c1", database="db1",
                                 max_steps=1, confirm_callback=callback)
                callback.assert_not_called()

    # ---- Multi-agent / tool tests ----

    def test_agent_ask_ai_tool(self, ai_service):
        """Agent calls ask_ai tool and returns answer."""
        tool_calls = [{"name": "ask_ai", "arguments": {"question": "What is a JOIN?"}}]
        with patch.object(ai_service, "_call_llm", return_value=("", tool_calls)):
            with patch.object(ai_service, "ask", return_value="A JOIN combines tables"):
                result = ai_service.agent("what is join", max_steps=1)
                assert any("JOIN" in s.observation for s in result.steps)

    def test_agent_generate_report_tool(self, ai_service):
        """Agent calls generate_report tool."""
        tool_calls = [{"name": "generate_report", "arguments": {"data": '{"count": 42}', "question": "how many?"}}]
        with patch.object(ai_service, "_call_llm", return_value=("", tool_calls)):
            with patch.object(ai_service, "_call_llm_text", return_value="There are 42 records"):
                result = ai_service.agent("report", max_steps=1)
                assert any("42" in s.observation for s in result.steps)

    def test_agent_tools_structure(self, ai_service):
        """All tools are properly defined."""
        tools = ai_service._agent_tools()
        names = [t["function"]["name"] for t in tools]
        assert "search_schema" in names
        assert "list_tables" in names
        assert "execute_sql" in names
        assert "ask_ai" in names
        assert "generate_report" in names
        assert len(tools) == 5
