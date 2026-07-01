"""Tests for AI service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


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

    def test_call_openai_error_returns_empty(self, ai_service):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.side_effect = Exception("API error")
            text, tools = ai_service._call_openai([{"role": "user", "content": "hi"}], 0.1)
            assert text == ""
            assert tools is None

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

    def test_review_sql_returns_report(self, ai_service):
        """review_sql returns a review report for a given SQL query."""
        test_sql = "SELECT * FROM users WHERE id = 1"
        mock_report = (
            "## 🔴 SECURITY ISSUES\n- Using `SELECT *` exposes all columns\n\n"
            "## 🟡 PERFORMANCE ISSUES\n- No issues found\n\n"
            "## 🔵 BEST PRACTICES\n- Avoid `SELECT *`, specify columns explicitly\n\n"
            "## 🟢 SUMMARY\n**Risk: LOW**"
        )
        with patch.object(ai_service, "_call_llm_text", return_value=mock_report):
            result = ai_service.review_sql(test_sql)
            assert "SECURITY" in result
            assert "RISK" in result or "risk" in result.lower()

    def test_review_sql_accepts_schema_context(self, ai_service):
        """review_sql passes schema context for deeper analysis."""
        sql = "DELETE FROM users"
        schema = "users(id INT PK, name VARCHAR, email VARCHAR)"
        with patch.object(ai_service, "_call_llm_text", return_value="HIGH RISK: Missing WHERE clause") as mock:
            result = ai_service.review_sql(sql, schema_context=schema)
            assert "HIGH RISK" in result
            # Verify schema context was included in the prompt
            call_args = mock.call_args[0][0]
            prompt_text = call_args[1]["content"]
            assert "users(id INT PK" in prompt_text or "schema_context" in prompt_text.lower()

    def test_review_sql_empty_on_failure(self, ai_service):
        """review_sql returns empty string on LLM failure."""
        with patch.object(ai_service, "_call_llm_text", return_value=""):
            result = ai_service.review_sql("SELECT 1")
            assert result == ""
