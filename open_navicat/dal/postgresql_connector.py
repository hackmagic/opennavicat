from __future__ import annotations

import time

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

from open_navicat.dal.base_connector import BaseConnector
from open_navicat.models import (
    ColumnInfo,
    ColumnMeta,
    ConnectionInfo,
    DatabaseInfo,
    ForeignKeyInfo,
    IndexInfo,
    QueryResult,
    TableInfo,
)


def _parse_cmd_tag(tag: str) -> int:
    parts = tag.split()
    return int(parts[-1]) if len(parts) >= 2 and parts[-1].isdigit() else 0


class PostgreSQLConnector(BaseConnector):
    def __init__(self, info: ConnectionInfo) -> None:
        self._info = info
        self._pool: asyncpg.Pool | None = None

    # ---- connection lifecycle ----

    async def connect(self) -> bool:
        if asyncpg is None:
            raise ImportError("asyncpg is required for PostgreSQL support: pip install asyncpg")
        try:
            self._pool = await asyncpg.create_pool(
                host=self._info.host,
                port=self._info.port or 5432,
                user=self._info.user,
                password=self._info.password,
                database=self._info.database or "postgres",
                min_size=self._info.pool_min,
                max_size=self._info.pool_max,
                timeout=self._info.connect_timeout,
            )
            return True
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def is_connected(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                return not conn.is_closed()
        except Exception:
            return False

    async def ping(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
                return True
        except Exception:
            return False

    # ---- metadata ----

    async def list_databases(self) -> list[DatabaseInfo]:
        sql = (
            "SELECT datname, pg_encoding_to_char(encoding) AS encoding, datcollate "
            "FROM pg_database WHERE datistemplate = false ORDER BY datname"
        )
        rows = await self._fetch_all(sql)
        return [
            DatabaseInfo(name=r[0], charset=r[1] or "UTF8", collation=r[2] or "en_US.UTF-8")
            for r in rows
        ]

    async def list_tables(self, database: str) -> list[str]:
        _ = database
        sql = (
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
        )
        rows = await self._fetch_all(sql)
        return [str(r[0]) for r in rows]

    async def list_views(self, database: str) -> list[str]:
        _ = database
        sql = (
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        rows = await self._fetch_all(sql)
        return [str(r[0]) for r in rows]

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        _ = database
        sql = (
            "SELECT specific_name, routine_type FROM information_schema.routines "
            "WHERE specific_schema = 'public' ORDER BY specific_name"
        )
        try:
            rows = await self._fetch_all(sql)
            return [(str(r[0]), str(r[1])) for r in rows]
        except Exception:
            return []

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        _ = database
        info = TableInfo(name=table, database=database)
        info.engine = "PostgreSQL"
        info.charset = "UTF8"
        info.collation = "en_US.UTF-8"

        tbl_sql = """
            SELECT c.reltuples::bigint,
                   pg_catalog.obj_description(c.oid, 'pg_class')
            FROM pg_catalog.pg_class c
            WHERE c.relname = $1 AND c.relkind = 'r'
        """
        rows = await self._fetch_all(tbl_sql, (table,))
        if rows:
            r = rows[0]
            info.row_count = r[0] or 0
            info.comment = r[1] or ""

        col_sql = """
            SELECT column_name, data_type, is_nullable, column_default,
                   character_maximum_length, numeric_precision, numeric_scale,
                   character_set_name, collation_name, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position
        """
        col_rows = await self._fetch_all(col_sql, (table,))
        if not col_rows:
            return info

        pk_sql = """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_catalog = kcu.constraint_catalog
             AND tc.constraint_schema = kcu.constraint_schema
             AND tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public' AND tc.table_name = $1
        """
        pk_rows = await self._fetch_all(pk_sql, (table,))
        pk_set = set(str(r[0]) for r in pk_rows)

        for r in col_rows:
            col_name = r[0]
            info.columns.append(ColumnInfo(
                name=col_name,
                data_type=r[1],
                nullable=(r[2] == "YES"),
                default=r[3],
                char_max_length=r[4],
                numeric_precision=r[5],
                numeric_scale=r[6],
                character_set=r[7] or "",
                collation=r[8] or "",
                is_primary_key=col_name in pk_set,
                is_auto_increment=(r[3] or "").startswith("nextval("),
            ))

        idx_sql = """
            SELECT i.relname, a.attname, ix.indisunique, ix.indisprimary, am.amname
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON ix.indexrelid = i.oid
            JOIN pg_am am ON i.relam = am.oid
            CROSS JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS ik(attnum, pos)
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ik.attnum
            WHERE t.relkind = 'r' AND t.relname = $1
            ORDER BY i.relname, ik.pos
        """
        idx_rows = await self._fetch_all(idx_sql, (table,))
        idx_map: dict[str, IndexInfo] = {}
        for r in idx_rows:
            name = r[0]
            if name not in idx_map:
                idx_map[name] = IndexInfo(
                    name=name,
                    is_unique=bool(r[2]),
                    is_primary=bool(r[3]),
                    index_type=r[4] or "BTREE",
                )
            idx_map[name].columns.append(r[1])
        info.indexes = list(idx_map.values())

        _fk_map = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}
        fk_sql = """
            SELECT con.conname, a.attname, fr.relname, fa.attname,
                   con.confdeltype, con.confupdtype
            FROM pg_constraint con
            JOIN pg_class t ON con.conrelid = t.oid
            JOIN pg_class fr ON con.confrelid = fr.oid
            CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ck(attnum, pos)
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
            CROSS JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS fk(attnum, fpos)
            JOIN pg_attribute fa ON fa.attrelid = fr.oid AND fa.attnum = fk.attnum
            WHERE con.contype = 'f' AND t.relname = $1 AND ck.pos = fk.fpos
            ORDER BY con.conname, ck.pos
        """
        fk_rows = await self._fetch_all(fk_sql, (table,))
        for r in fk_rows:
            info.foreign_keys.append(ForeignKeyInfo(
                name=r[0], column=r[1], ref_table=r[2],
                ref_column=r[3],
                on_delete=_fk_map.get(r[4], "NO ACTION"),
                on_update=_fk_map.get(r[5], "NO ACTION"),
            ))

        return info

    # ---- query execution ----

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        result = QueryResult()
        start = time.perf_counter()
        try:
            async with self._pool.acquire() as conn:
                stmt = await conn.prepare(sql)
                attrs = stmt.get_attributes()
                args = list(params) if params else []

                if attrs:
                    rows = await stmt.fetch(*args)
                    result.columns = [
                        ColumnMeta(name=a.name, data_type=str(a.type))
                        for a in attrs
                    ]
                    result.rows = [list(r.values()) for r in rows]
                    result.row_count = len(result.rows)
                else:
                    tag = await conn.execute(sql, *args)
                    result.affected_rows = _parse_cmd_tag(tag)

            result.execution_time_ms = (time.perf_counter() - start) * 1000
        except Exception as e:
            result.success = False
            result.error_message = str(e)
        return result

    async def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        async with self._pool.acquire() as conn:
            tag = await conn.executemany(sql, params_list)
            return _parse_cmd_tag(tag)

    async def fetch_page(
        self, database: str, table: str,
        offset: int, limit: int,
        order_by: str | None = None,
        order_dir: str = "ASC",
    ) -> QueryResult:
        _ = database
        order = f'ORDER BY "{order_by}" {order_dir}' if order_by else ""
        sql = f'SELECT * FROM "public"."{table}" {order} LIMIT $1 OFFSET $2'
        return await self.execute(sql, (limit, offset))

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        columns = list(rows[0].keys())
        placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
        col_names = ", ".join(f'"{c}"' for c in columns)
        sql = f'INSERT INTO "public"."{table}" ({col_names}) VALUES ({placeholders})'
        params = [tuple(r[c] for c in columns) for r in rows]
        async with self._pool.acquire() as conn:
            await conn.executemany(sql, params)
        return len(rows)

    async def update_row(
        self, database: str, table: str,
        values: dict, where: dict,
    ) -> int:
        _ = database
        n = len(values)
        set_clause = ", ".join(f'"{k}" = ${i+1}' for i, k in enumerate(values))
        where_clause = " AND ".join(f'"{k}" = ${n+i+1}' for i, k in enumerate(where))
        sql = f'UPDATE "public"."{table}" SET {set_clause} WHERE {where_clause}'
        result = await self.execute(sql, tuple(list(values.values()) + list(where.values())))
        return result.affected_rows

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        _ = database
        where_clause = " AND ".join(f'"{k}" = ${i+1}' for i, k in enumerate(where))
        sql = f'DELETE FROM "public"."{table}" WHERE {where_clause}'
        result = await self.execute(sql, tuple(where.values()))
        return result.affected_rows

    # ---- private helpers ----

    async def _fetch_all(self, sql: str, params: tuple = ()) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql, *params)
