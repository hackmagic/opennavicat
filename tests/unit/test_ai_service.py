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
        with patch.object(ai_service, "_call_openai", return_value="OK") as mock:
            result = ai_service._call_llm([{"role": "user", "content": "hi"}])
            mock.assert_called_once()
            assert result == "OK"

    def test_call_llm_routes_to_ollama(self, ai_service):
        ai_service._provider = "ollama"
        with patch.object(ai_service, "_call_ollama", return_value="OK") as mock:
            ai_service._call_llm([{"role": "user", "content": "hi"}])
            mock.assert_called_once()

    def test_call_llm_routes_to_deepseek(self, ai_service):
        ai_service._provider = "deepseek"
        with patch.object(ai_service, "_call_deepseek", return_value="OK") as mock:
            ai_service._call_llm([{"role": "user", "content": "hi"}])
            mock.assert_called_once()

    def test_call_llm_routes_to_custom(self, ai_service):
        ai_service._provider = "custom"
        with patch.object(ai_service, "_call_custom", return_value="OK") as mock:
            ai_service._call_llm([{"role": "user", "content": "hi"}])
            mock.assert_called_once()

    def test_call_openai_success(self, ai_service):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello"))]
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = mock_response
            result = ai_service._call_openai([{"role": "user", "content": "hi"}], 0.1)
            assert result == "Hello"

    def test_call_openai_error_returns_empty(self, ai_service):
        with patch("openai.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.side_effect = Exception("API error")
            result = ai_service._call_openai([{"role": "user", "content": "hi"}], 0.1)
            assert result == ""

    def test_nl2sql(self, ai_service):
        with patch.object(ai_service, "_call_llm", return_value="SELECT * FROM users"):
            result = ai_service.nl2sql("show all users", "users(id, name)")
            assert "SELECT" in result

    def test_optimize(self, ai_service):
        with patch.object(ai_service, "_call_llm", return_value="Use index on column"):
            result = ai_service.optimize("SELECT * FROM t WHERE x=1")
            assert "index" in result.lower() or "use" in result.lower()

    def test_explain_query(self, ai_service):
        with patch.object(ai_service, "_call_llm", return_value="This query selects all rows"):
            result = ai_service.explain_query("SELECT * FROM t")
            assert "select" in result.lower()

    def test_fix_sql(self, ai_service):
        with patch.object(ai_service, "_call_llm", return_value="SELECT * FROM t"):
            result = ai_service.fix_sql("SELCT * FORM t")
            assert result

    def test_generate_data_returns_list(self, ai_service):
        from open_navicat.models.table_schema import ColumnInfo, TableInfo
        table_info = TableInfo(name="users", database="testdb")
        table_info.columns = [ColumnInfo(name="id", data_type="INT"), ColumnInfo(name="name", data_type="VARCHAR")]
        with patch.object(ai_service, "_call_llm", return_value='[{"id": 1, "name": "test"}]'):
            result = ai_service.generate_data(table_info, 1)
            assert isinstance(result, list)
            assert len(result) == 1

    def test_generate_data_invalid_json_returns_empty(self, ai_service):
        from open_navicat.models.table_schema import ColumnInfo, TableInfo
        table_info = TableInfo(name="users", database="testdb")
        table_info.columns = [ColumnInfo(name="id", data_type="INT")]
        with patch.object(ai_service, "_call_llm", return_value="not json"):
            result = ai_service.generate_data(table_info, 1)
            assert result == []

    def test_chat_appends_history(self, ai_service):
        with patch.object(ai_service, "_call_llm", return_value="Hi there"):
            result = ai_service.chat("Hello")
            assert result == "Hi there"
            assert len(ai_service._chat_history) == 2  # user + assistant

    def test_chat_history_capped(self, ai_service):
        ai_service._chat_history = [{"role": "user", "content": f"msg{i}"} for i in range(80)]
        with patch.object(ai_service, "_call_llm", return_value="OK"):
            ai_service.chat("test")
            assert len(ai_service._chat_history) <= 42  # capped at 20 + new pair

    def test_test_config_success(self, ai_service):
        with patch.object(ai_service, "_call_llm", return_value="OK"):
            ok, msg = ai_service.test_config()
            assert ok is True

    def test_test_config_failure(self, ai_service):
        with patch.object(ai_service, "_call_llm", side_effect=Exception("Connection refused")):
            ok, msg = ai_service.test_config()
            assert ok is False
            assert "refused" in msg.lower() or "connection" in msg.lower()
