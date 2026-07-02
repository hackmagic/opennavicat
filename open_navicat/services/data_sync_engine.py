"""Data Synchronization Engine — row-level comparison between two tables.

Compares two tables (source vs target), detects row-level differences,
and generates INSERT / UPDATE / DELETE DML to sync target to source.
Supports both MySQL and PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from open_navicat.dal.connection_pool import _loop as pool_loop
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.models.connection import ConnectionInfo
from open_navicat.models.table_schema import ColumnInfo


@dataclass
class RowDiff:
    """Difference for a single row."""
    action: str  # insert | update | delete
    pk_values: dict[str, object]
    set_values: dict[str, object] = field(default_factory=dict)
    old_values: dict[str, object] = field(default_factory=dict)


@dataclass
class DataCompareResult:
    """Result of comparing two tables."""
    source_rows: int = 0
    target_rows: int = 0
    inserts: list[RowDiff] = field(default_factory=list)
    updates: list[RowDiff] = field(default_factory=list)
    deletes: list[RowDiff] = field(default_factory=list)
    columns: list[ColumnInfo] = field(default_factory=list)
    pk_columns: list[str] = field(default_factory=list)
    source_table: str = ""
    target_table: str = ""

    @property
    def total_diffs(self) -> int:
        return len(self.inserts) + len(self.updates) + len(self.deletes)


class DataSyncEngine:
    """Row-level data comparison and sync between two database tables."""

    def __init__(self) -> None:
        self._batch_size = 5000

    def compare_tables(
        self,
        source_conn_id: str,
        source_database: str,
        source_table: str,
        target_conn_id: str,
        target_database: str,
        target_table: str = "",
        incremental_column: str = "",
        last_sync_value: str = "",
    ) -> DataCompareResult:
        """Compare rows between source and target tables. If incremental_column is set, only sync rows where that column > last_sync_value."""
        target_table = target_table or source_table
        result = DataCompareResult(
            source_table=source_table,
            target_table=target_table,
        )

        src_conn = connection_pool.get(source_conn_id)
        tgt_conn = connection_pool.get(target_conn_id)
        if not src_conn or not tgt_conn:
            raise ConnectionError("Source or target connection not found")

        # Detect engine from connector info
        src_engine = getattr(src_conn, "_info", None)
        is_pg = src_engine and getattr(src_engine, "engine", "mysql") == "postgresql"
        q = '"' if is_pg else "`"

        # Get column metadata from source
        if is_pg:
            col_info_sql = (
                "SELECT column_name, data_type, is_nullable, "
                "character_maximum_length, numeric_precision, numeric_scale, "
                "column_default, '', column_description("
                "attrelid::regclass, attnum) "
                "FROM information_schema.columns "
                "JOIN pg_attribute ON attname = column_name "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position"
            )
        else:
            col_info_sql = (
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, "
                "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, "
                "COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                "ORDER BY ORDINAL_POSITION"
            )
        col_meta = pool_loop.run_until_complete(
            src_conn.execute(col_info_sql, (source_database, source_table))
        )

        columns: list[ColumnInfo] = []
        col_names: list[str] = []
        for r in (col_meta.rows or []):
            col = ColumnInfo(
                name=r[0], data_type=r[1], nullable=(r[2] == "YES"),
                char_max_length=r[3], numeric_precision=r[4],
                numeric_scale=r[5], default=r[6], comment=r[8] or "",
                is_auto_increment=(not is_pg and "auto_increment" in (r[7] or "")),
            )
            columns.append(col)
            col_names.append(r[0])
        result.columns = columns

        if not col_names:
            return result

        # Detect PK columns
        if is_pg:
            pk_sql = (
                "SELECT a.attname "
                "FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = %s::regclass AND i.indisprimary "
                "ORDER BY a.attnum"
            )
        else:
            pk_sql = (
                "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                "AND CONSTRAINT_NAME='PRIMARY' ORDER BY ORDINAL_POSITION"
            )
        pk_meta = pool_loop.run_until_complete(
            src_conn.execute(pk_sql, (source_table if is_pg else (source_database, source_table)))
        )
        pk_cols = [r[0] for r in (pk_meta.rows or [])]
        if not pk_cols:
            pk_cols = col_names[:1]
        result.pk_columns = pk_cols

        # Fetch all rows from both sides
        inc_filter = f" WHERE {q}{incremental_column}{q} > '{last_sync_value}'" if incremental_column else ""
        cols_csv = ", ".join(f"{q}{c}{q}" for c in col_names)
        src_sql = f"SELECT {cols_csv} FROM {q}{source_database}{q}.{q}{source_table}{q}{inc_filter}"
        tgt_sql = f"SELECT {cols_csv} FROM {q}{target_database}{q}.{q}{target_table}{q}"

        src_rows = pool_loop.run_until_complete(src_conn.execute(src_sql))
        tgt_rows = pool_loop.run_until_complete(tgt_conn.execute(tgt_sql))

        result.source_rows = len(src_rows.rows or [])
        result.target_rows = len(tgt_rows.rows or [])

        # Build lookup keyed by PK tuple
        def pk_key(row: tuple) -> tuple:
            return tuple(row[col_names.index(pk)] for pk in pk_cols)

        src_map: dict[tuple, tuple] = {}
        for row in (src_rows.rows or []):
            src_map[pk_key(row)] = row

        tgt_map: dict[tuple, tuple] = {}
        for row in (tgt_rows.rows or []):
            tgt_map[pk_key(row)] = row

        # Find inserts (in source, not in target)
        for pk, row in src_map.items():
            if pk not in tgt_map:
                result.inserts.append(RowDiff(
                    action="insert",
                    pk_values=dict(zip(pk_cols, pk)),
                    set_values=dict(zip(col_names, row)),
                ))

        # Find deletes (in target, not in source)
        for pk, row in tgt_map.items():
            if pk not in src_map:
                result.deletes.append(RowDiff(
                    action="delete",
                    pk_values=dict(zip(pk_cols, pk)),
                ))

        # Find updates (in both, different values)
        for pk, src_row in src_map.items():
            tgt_row = tgt_map.get(pk)
            if tgt_row is None:
                continue
            diff_values = {}
            old_values = {}
            for i, col in enumerate(col_names):
                sv = src_row[i]
                tv = tgt_row[i]
                if sv != tv:
                    diff_values[col] = sv
                    old_values[col] = tv
            if diff_values:
                result.updates.append(RowDiff(
                    action="update",
                    pk_values=dict(zip(pk_cols, pk)),
                    set_values=diff_values,
                    old_values=old_values,
                ))

        return result

    def generate_sync_script(self, result: DataCompareResult, engine: str = "mysql") -> str:
        """Generate DML script to sync target to source.

        Args:
            engine: "mysql" or "postgresql" — controls quoting.
        """
        if not result.columns:
            return ""
        is_pg = engine == "postgresql"
        q = '"' if is_pg else "`"
        stmts: list[str] = []
        db_table = f"{q}{result.target_table}{q}"

        def quote(v):
            if v is None:
                return "NULL"
            if isinstance(v, (int, float)):
                return str(v)
            return "'" + str(v).replace("'", "''") + "'"

        # INSERT
        for diff in result.inserts:
            cols = ", ".join(f"{q}{k}{q}" for k in diff.set_values)
            vals = ", ".join(quote(v) for v in diff.set_values.values())
            stmts.append(f"INSERT INTO {db_table} ({cols}) VALUES ({vals});")

        # UPDATE
        for diff in result.updates:
            sets = ", ".join(f"{q}{k}{q} = {quote(v)}" for k, v in diff.set_values.items())
            where = " AND ".join(
                f"{q}{k}{q} = {quote(v)}" if v is not None else f"{q}{k}{q} IS NULL"
                for k, v in diff.pk_values.items()
            )
            stmts.append(f"UPDATE {db_table} SET {sets} WHERE {where};")

        # DELETE
        for diff in result.deletes:
            where = " AND ".join(
                f"{q}{k}{q} = {quote(v)}" if v is not None else f"{q}{k}{q} IS NULL"
                for k, v in diff.pk_values.items()
            )
            stmts.append(f"DELETE FROM {db_table} WHERE {where};")

        return "\n".join(stmts)


data_sync_engine = DataSyncEngine()
