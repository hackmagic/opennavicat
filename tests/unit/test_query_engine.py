"""Unit tests for QueryEngine."""
from __future__ import annotations

from unittest.mock import patch

from open_navicat.models.query_result import QueryResult
from open_navicat.services.query_engine import QueryEngine, query_engine


class TestQueryEngine:
    def setup_method(self) -> None:
        self._engine = QueryEngine()

    def test_singleton(self) -> None:
        assert query_engine is not None

    def test_execute_no_connection(self) -> None:
        with patch("open_navicat.services.query_engine.connection_pool") as mock_pool:
            mock_pool.get.return_value = None
            result = self._engine.execute("c1", "SELECT 1")
            assert result.success is False
            assert "No active connection" in result.error_message

    def test_execute_calls_connector(self) -> None:
        result = QueryResult(success=True, columns=[], rows=[[1]])
        with (
            patch("open_navicat.services.query_engine.connection_pool"),
            patch("open_navicat.services.query_engine._pool_loop") as mock_loop,
            patch("open_navicat.services.query_engine.query_cache") as mock_cache,
        ):
            mock_cache.get.return_value = None
            mock_loop.return_value.run_until_complete.return_value = result
            out = self._engine.execute("c1", "SELECT 1")
            assert out.success is True
            mock_loop.return_value.run_until_complete.assert_called_once()

    def test_execute_returns_cached(self) -> None:
        cached = QueryResult(success=True, columns=[], rows=[[42]])
        with (
            patch("open_navicat.services.query_engine.connection_pool"),
            patch("open_navicat.services.query_engine.query_cache") as mock_cache,
        ):
            mock_cache.get.return_value = cached
            out = self._engine.execute("c1", "SELECT 1")
            assert out.rows == [[42]]

    def test_execute_non_select_skips_cache(self) -> None:
        result = QueryResult(success=True, affected_rows=2)
        with (
            patch("open_navicat.services.query_engine.connection_pool"),
            patch("open_navicat.services.query_engine._pool_loop") as mock_loop,
            patch("open_navicat.services.query_engine.query_cache") as mock_cache,
        ):
            mock_loop.return_value.run_until_complete.return_value = result
            out = self._engine.execute("c1", "INSERT INTO t VALUES (1)")
            assert out.affected_rows == 2
            mock_cache.set.assert_not_called()

    def test_explain(self) -> None:
        with (
            patch("open_navicat.services.query_engine.connection_pool") as mock_pool,
            patch("open_navicat.services.query_engine._pool_loop") as mock_loop,
        ):
            mock_pool.get.return_value = mock_pool
            result = QueryResult(success=True, plan="EXPLAIN")
            mock_loop.return_value.run_until_complete.return_value = result
            out = self._engine.explain("c1", "SELECT 1")
            assert out.plan == "EXPLAIN"

    def test_explain_format_json(self) -> None:
        with (
            patch("open_navicat.services.query_engine.connection_pool") as mock_pool,
            patch("open_navicat.services.query_engine._pool_loop") as mock_loop,
        ):
            mock_pool.get.return_value = mock_pool
            result = QueryResult(success=True, plan="JSON")
            mock_loop.return_value.run_until_complete.return_value = result
            out = self._engine.explain_format_json("c1", "SELECT 1")
            assert out.plan == "JSON"

    def test_count_rows_no_connection(self) -> None:
        with patch("open_navicat.services.query_engine.connection_pool") as mock_pool:
            mock_pool.get.return_value = None
            assert self._engine.count_rows("c1", "db", "t") == 0
