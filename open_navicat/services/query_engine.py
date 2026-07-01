"""Query engine — executes SQL, manages result sets, and provides pagination."""

from __future__ import annotations

from open_navicat.dal.connection_pool import _loop as pool_loop
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.models.query_result import QueryResult


class QueryEngine:
    """Service layer for SQL query execution and result management."""

    def execute(self, connection_id: str, sql: str) -> QueryResult:
        connector = connection_pool.get(connection_id)
        if not connector:
            return QueryResult(success=False, error_message="No active connection")
        loop = pool_loop
        return loop.run_until_complete(connector.execute(sql))

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


# Module-level singleton
query_engine = QueryEngine()
