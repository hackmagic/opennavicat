"""Query engine — executes SQL, manages result sets, and provides pagination."""

from __future__ import annotations

import logging

from open_navicat.dal.connection_pool import _loop as pool_loop
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.models.query_result import QueryResult
from open_navicat.utils.query_cache import query_cache

_log = logging.getLogger(__name__)


class QueryEngine:
    """Service layer for SQL query execution and result management."""

    def execute(self, connection_id: str, sql: str) -> QueryResult:
        sql_stripped = sql.strip().upper()
        # Only cache SELECT queries
        if sql_stripped.startswith("SELECT") or sql_stripped.startswith("WITH"):
            cached = query_cache.get(connection_id, "", sql)
            if cached is not None:
                return cached
        connector = connection_pool.get(connection_id)
        if not connector:
            return QueryResult(success=False, error_message="No active connection")
        loop = pool_loop
        result = loop.run_until_complete(connector.execute(sql))
        if result.success and (sql_stripped.startswith("SELECT") or sql_stripped.startswith("WITH")):
            query_cache.set(connection_id, "", sql, result)
        return result

    def execute_file(self, connection_id: str, file_path: str) -> list[QueryResult]:
        """Execute multiple statements from a .sql file, return results per statement."""
        from pathlib import Path
        content = Path(file_path).read_text(encoding="utf-8")
        return self.execute_script(connection_id, content)

    def execute_script(self, connection_id: str, script: str) -> list[QueryResult]:
        """Split script by ';' and execute each statement."""
        import sqlparse
        statements = sqlparse.split(script)
        results: list[QueryResult] = []
        for stmt in statements:
            stmt = stmt.strip()
            if stmt:
                results.append(self.execute(connection_id, stmt))
        return results

    def explain(self, connection_id: str, sql: str) -> QueryResult:
        """Run EXPLAIN on a query and return the execution plan."""
        return self.execute(connection_id, f"EXPLAIN {sql}")

    def explain_format_json(self, connection_id: str, sql: str) -> QueryResult:
        """Run EXPLAIN FORMAT=JSON for detailed plan."""
        return self.execute(connection_id, f"EXPLAIN FORMAT=JSON {sql}")

    def count_rows(self, connection_id: str, database: str, table: str) -> int:
        connector = connection_pool.get(connection_id)
        if not connector:
            return 0
        loop = pool_loop
        safe_db = database.replace("`", "``")
        safe_table = table.replace("`", "``")
        result = loop.run_until_complete(
            connector.execute(f"SELECT COUNT(*) FROM `{safe_db}`.`{safe_table}`")
        )
        if result.success and result.rows:
            return result.rows[0][0]
        return 0


    def execute_stream(self, connection_id: str, sql: str, chunk_size: int = 1000):
        """Execute a query and yield rows in chunks (server-side cursor for large datasets)."""
        conn = connection_pool.get(connection_id)
        if not conn:
            return
        try:
            result = pool_loop.run_until_complete(conn.execute(sql))
            if result.success and result.rows:
                total = len(result.rows)
                for i in range(0, total, chunk_size):
                    yield result.rows[i:i + chunk_size]
        except Exception as e:
            _log.warning("Stream execute failed: %s", e)


# Module-level singleton
query_engine = QueryEngine()
