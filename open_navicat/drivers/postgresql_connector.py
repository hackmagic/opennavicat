from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.errors import DriverNotFoundError
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
from open_navicat.sql.quoting import quote_identifier, quote_qualified

logger = logging.getLogger("opennavicat.postgresql")

#: Schema assumed when a caller names a table without one.  PostgreSQL creates
#: user objects here by default, which is why bare names passed by the CLI
#: commands and the schema sync engine keep resolving.
_DEFAULT_SCHEMA = "public"

#: Schemas the object browser must never list.  PostgreSQL keeps its catalogs in
#: ``pg_catalog`` and every other internal namespace (``pg_toast``, ``pg_temp_*``)
#: starts with ``pg_``, so ``!~ '^pg_'`` covers them without an allow-list that
#: would go stale; ``information_schema`` is an ordinary schema name and needs
#: its own exclusion.
_NON_SYSTEM_SCHEMAS = "n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'"

#: Same exclusion for queries that read schemas out of ``information_schema``
#: views, where the column holding the schema is named differently.
_NON_SYSTEM_ROUTINE_SCHEMAS = "routine_schema !~ '^pg_' AND routine_schema <> 'information_schema'"


def _qualified_name(schema: str, name: str) -> str:
    """Render a catalog object the way the object tree and grid expect it.

    ``public`` is PostgreSQL's default search path, so qualifying it would only
    add noise; every other schema must be qualified, otherwise two tables with
    the same name in different schemas become indistinguishable in the tree.
    """
    if not schema or schema == _DEFAULT_SCHEMA:
        return name
    return f"{schema}.{name}"


def _bare_name(name: str | None) -> str:
    """Return the table part of a possibly schema-qualified name.

    Splits on the *first* dot only, matching :func:`quote_qualified`: further
    dots belong to the (unusual but legal) table name itself, and ``rsplit``
    would then attribute the object to the wrong schema.
    """
    text = str(name or "")
    _schema, separator, table = text.partition(".")
    return table if separator else text


def _schema_of(name: str | None) -> str | None:
    """Return the schema part of a qualified name, or ``None`` when bare.

    ``None`` means "the caller said nothing about the schema", which must not be
    read as ``public``: an unqualified name resolves through ``search_path``,
    and pinning it to ``public`` breaks custom and ``"$user"`` search paths.
    """
    text = str(name or "")
    schema, separator, _table = text.partition(".")
    return schema if separator and schema else None


def _char_key(value: object) -> str:
    """Normalise a PostgreSQL ``"char"`` value to its single character.

    asyncpg decodes ``"char"`` columns as ``bytes``, so the raw value is ``b"c"``
    for CASCADE.  ``str()`` on that yields ``"b'c'"``, which matches no lookup
    table; this accepts bytes, str and None and always returns a plain character
    (or ``"a"`` for NO ACTION when nothing usable was returned).
    """
    if value is None:
        return "a"
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")[:1] or "a"
    text = str(value)
    return text[:1] or "a"


def _looks_multi_statement(sql: str) -> bool:
    """True when ``sql`` holds more than one statement.

    Scans for a top-level ``;`` that is not a terminator, skipping single and
    double quoted text, dollar-quoted bodies (``$$ ... $$``, used by plpgsql
    functions -- those contain semicolons but are one statement) and
    ``--``/``/* */`` comments.  Only the simple-query path can run such text,
    because ``prepare()`` refuses it outright.
    """
    depth_quote: str | None = None
    dollar_tag = ""
    i = 0
    n = len(sql)
    last_semicolon = -1
    earlier_semicolon = -1
    while i < n:
        ch = sql[i]
        if depth_quote:
            if dollar_tag:
                if sql.startswith(dollar_tag, i):
                    i += len(dollar_tag)
                    dollar_tag = ""
                    depth_quote = None
                    continue
                i += 1
                continue
            if ch == depth_quote:
                # Doubled quote is an escaped literal quote, not a terminator.
                if i + 1 < n and sql[i + 1] == depth_quote:
                    i += 2
                    continue
                depth_quote = None
            elif ch == "\\" and depth_quote == "'":
                i += 2
                continue
            i += 1
            continue
        if ch in ("'", '"'):
            depth_quote = ch
            i += 1
            continue
        if ch == "$":
            end = sql.find("$", i + 1)
            if end != -1 and all(c.isalnum() or c == "_" for c in sql[i + 1 : end]):
                dollar_tag = sql[i : end + 1]
                depth_quote = "$"
                i = end + 1
                continue
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            nl = sql.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch == ";":
            if last_semicolon != -1:
                earlier_semicolon = last_semicolon
            last_semicolon = i
        i += 1
    # One statement may end with a semicolon; a second top-level semicolon
    # (even when the script merely ends with `;`) means there are two.
    if last_semicolon == -1:
        return False
    # Trailing non-terminator text after the last semicolon is a second
    # statement; so is a second semicolon anywhere at top level.
    return bool(earlier_semicolon != -1 or sql[last_semicolon + 1 :].strip())


def _parse_cmd_tag(tag: str | None) -> int:
    """Extract the affected-row count from an asyncpg command tag.

    ``asyncpg.Connection.executemany`` returns ``None`` instead of a tag, so
    callers must not assume a string: without this guard a bulk insert raised
    ``AttributeError: 'NoneType' object has no attribute 'split'`` and the write
    was reported as failed even though every row had been inserted.
    """
    if not tag:
        return 0
    parts = str(tag).split()
    return int(parts[-1]) if len(parts) >= 2 and parts[-1].isdigit() else 0


class PostgreSQLConnector(BaseConnector):
    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__()
        self._info = info
        self._pool: asyncpg.Pool | None = None
        #: One cached session per *sibling* database.  A pool is bound to exactly
        #: one database, so listing objects of another database requires a
        #: separate connection; the cache keeps tree expansion from opening a
        #: new session per node.  ``disconnect`` closes every entry.
        self._database_links: dict[str, asyncpg.Connection] = {}

    # ---- connection lifecycle ----

    def _bound_database(self) -> str:
        """Database the pool's sessions are connected to."""
        return self._info.database or "postgres"

    def _connection_options(self, database: str) -> dict[str, object]:
        """Build asyncpg kwargs for a session bound to ``database``.

        Pool creation and the on-demand sibling connections must agree on
        host/port/credentials/timeouts, so both derive them from here.
        """
        return {
            "host": self._info.host,
            "port": self._info.port or 5432,
            "user": self._info.user,
            "password": self._info.password,
            "database": database,
            "timeout": self._info.connect_timeout,
        }

    async def connect(self) -> bool:
        if asyncpg is None:
            raise DriverNotFoundError(
                "PostgreSQL driver (asyncpg) is not installed; "
                "install with: pip install open-navicat[postgresql]"
            )
        # A repeated connect() on the same instance must not leave the sessions
        # opened for a previous pool's sibling databases behind.
        await self._close_database_links()
        try:
            self._pool = await asyncpg.create_pool(
                **self._connection_options(self._bound_database()),
                min_size=self._info.pool_min,
                max_size=self._info.pool_max,
            )
            return True
        except Exception as exc:
            self._last_error = exc
            return False

    async def disconnect(self) -> None:
        """Close the pool *and* every sibling-database connection.

        Sibling sessions are opened lazily for cross-database listings; closing
        only the pool would leave those server sessions alive until the process
        exits, which is a leak on every database switch.
        """
        await self._close_database_links()
        pool = self._pool
        self._pool = None
        if pool is not None:
            await pool.close()

    async def _close_database_links(self) -> None:
        """Close and forget every cached sibling-database session."""
        links = self._database_links
        self._database_links = {}
        for database, conn in links.items():
            try:
                await conn.close()
            except Exception as exc:
                # Cleanup must not turn into the error the caller sees; a
                # session the server already dropped can fail to close.
                logger.warning(
                    "PostgreSQL could not close the connection to database %r: %s",
                    database,
                    exc,
                )

    async def _open_database_connection(self, database: str) -> asyncpg.Connection:
        """Open a standalone session to ``database`` and cache it.

        PostgreSQL has no cross-database catalog reads ("cross-database
        references are not implemented"), and every asyncpg connection is bound
        to the database named in its startup packet, so this is the only correct
        way to read another database's catalogs.
        """
        if asyncpg is None:
            raise DriverNotFoundError(
                "PostgreSQL driver (asyncpg) is not installed; "
                "install with: pip install open-navicat[postgresql]"
            )
        conn = await asyncpg.connect(**self._connection_options(database))
        self._database_links[database] = conn
        return conn

    async def _database_connection(self, database: str) -> asyncpg.Connection:
        """Return the cached session for ``database``, replacing a dead one."""
        conn = self._database_links.get(database)
        if conn is not None:
            if not conn.is_closed():
                return conn
            # A server restart or idle timeout leaves a closed handle; it cannot
            # be revived, so forget it and open a fresh session.
            self._database_links.pop(database, None)
        return await self._open_database_connection(database)

    @asynccontextmanager
    async def _connection(self, database: str | None = None) -> AsyncIterator[asyncpg.Connection]:
        """Yield a session bound to ``database`` (the pool's own by default)."""
        pool = self._pool
        if pool is None:
            raise RuntimeError("PostgreSQL connection is not open")
        target = (database or "").strip() or self._bound_database()
        if target == self._bound_database():
            async with pool.acquire() as conn:
                yield conn
            return
        yield await self._database_connection(target)

    async def is_connected(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._require_pool().acquire() as conn:
                return not conn.is_closed()
        except Exception:
            return False

    async def ping(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._require_pool().acquire() as conn:
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

    def _note_listing_failure(
        self, operation: str, database: str, exc: BaseException
    ) -> None:
        """Record and log a failed listing instead of hiding it.

        Listing methods still return ``[]`` so the object tree keeps rendering,
        but a connection or permission failure is not "this database has no
        objects": keeping the cause in ``last_error`` (which
        ``connection_pool`` diagnostics surface) and in the log is what lets a
        user tell the two apart.
        """
        self._last_error = exc
        logger.warning(
            "PostgreSQL %s failed for database %r: %s",
            operation,
            database,
            exc,
        )

    async def list_tables(self, database: str) -> list[str]:
        """Tables of ``database`` across every user schema.

        ``database`` is honoured rather than ignored: the tree expands one node
        per database, and reading the pool's database for all of them made every
        node show the same (often empty) list.  Schemas other than ``public``
        are listed because real deployments rarely keep everything in ``public``.
        """
        sql = (
            "SELECT n.nspname, c.relname "
            "FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') "
            f"AND {_NON_SYSTEM_SCHEMAS} "
            "ORDER BY n.nspname, c.relname"
        )
        try:
            rows = await self._fetch_all(sql, database=database)
        except Exception as exc:
            self._note_listing_failure("list_tables", database, exc)
            return []
        return [_qualified_name(str(r[0]), str(r[1])) for r in rows]

    async def list_tables_with_info(self, database: str) -> list[dict]:
        """Table list with the metadata the Table List grid renders.

        The inherited stub only echoes names with blank metadata, which is why
        the grid showed headers and no rows.  ``auto_increment`` is ``None`` and
        ``update_time`` is ``""`` on purpose: PostgreSQL exposes no per-table
        auto-increment counter or last-write timestamp, and substituting
        autovacuum/analyze times would misreport the data.  ``data_length`` is
        the real on-disk footprint (``pg_total_relation_size`` also counts the
        partitions of a partitioned table) and ``engine`` the access method,
        normally ``heap``.
        """
        sql = (
            "SELECT n.nspname, c.relname, pg_catalog.pg_total_relation_size(c.oid), am.amname "
            "FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_catalog.pg_am am ON am.oid = c.relam "
            "WHERE c.relkind IN ('r', 'p') "
            f"AND {_NON_SYSTEM_SCHEMAS} "
            "ORDER BY n.nspname, c.relname"
        )
        try:
            rows = await self._fetch_all(sql, database=database)
        except Exception as exc:
            self._note_listing_failure("list_tables_with_info", database, exc)
            return []
        return [
            {
                "name": _qualified_name(str(r[0]), str(r[1])),
                "auto_increment": None,
                "update_time": "",
                "data_length": int(r[2] or 0),
                "engine": str(r[3] or "PostgreSQL"),
            }
            for r in rows
        ]

    async def list_views(self, database: str) -> list[str]:
        sql = (
            "SELECT n.nspname, c.relname "
            "FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'v' "
            f"AND {_NON_SYSTEM_SCHEMAS} "
            "ORDER BY n.nspname, c.relname"
        )
        try:
            rows = await self._fetch_all(sql, database=database)
        except Exception as exc:
            self._note_listing_failure("list_views", database, exc)
            return []
        return [_qualified_name(str(r[0]), str(r[1])) for r in rows]

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        """User routines of ``database`` as ``(name, routine_type)`` pairs.

        ``information_schema.routines`` is per-database, so this has to run on a
        session bound to the requested database.  ``routine_name`` is reported
        rather than ``specific_name``: PostgreSQL appends ``_<oid>`` to
        ``specific_name`` (``noop_fn_24686``), which is not a name anyone can
        call or drop.  Overloaded routines therefore collapse to one entry per
        name, which matches how the other connectors present them.
        """
        sql = (
            "SELECT routine_schema, routine_name, routine_type "
            "FROM information_schema.routines "
            f"WHERE {_NON_SYSTEM_ROUTINE_SCHEMAS} "
            "ORDER BY routine_schema, routine_name"
        )
        try:
            rows = await self._fetch_all(sql, database=database)
        except Exception as exc:
            self._note_listing_failure("list_routines", database, exc)
            return []
        seen: set[tuple[str, str]] = set()
        routines: list[tuple[str, str]] = []
        for r in rows:
            entry = (_qualified_name(str(r[0]), str(r[1])), str(r[2] or "PROCEDURE"))
            if entry in seen:
                continue
            seen.add(entry)
            routines.append(entry)
        return routines

    async def list_triggers(self, database: str) -> list[tuple[str, str]]:
        """User-defined triggers as ``(trigger_name, table_name)`` pairs.

        Internal constraint triggers are excluded.  The trigger name stays bare
        because a trigger is only addressable together with its table
        (``DROP TRIGGER name ON schema.table``); the table follows the naming
        contract (``schema.name`` outside ``public``) so two same-named triggers
        on different schemas do not look identical.
        """
        sql = (
            "SELECT n.nspname, c.relname, t.tgname "
            "FROM pg_catalog.pg_trigger t "
            "JOIN pg_catalog.pg_class c ON t.tgrelid = c.oid "
            "JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid "
            f"WHERE NOT t.tgisinternal AND {_NON_SYSTEM_SCHEMAS} "
            "ORDER BY n.nspname, c.relname, t.tgname"
        )
        try:
            rows = await self._fetch_all(sql, database=database)
        except Exception as exc:
            self._note_listing_failure("list_triggers", database, exc)
            return []
        return [(str(r[2]), _qualified_name(str(r[0]), str(r[1]))) for r in rows]

    async def _exact_row_count(self, database: str, schema: str, table: str) -> int:
        """Exact ``COUNT(*)`` for one table, or 0 when it cannot be read."""
        sql = (
            f"SELECT count(*) FROM {quote_identifier(schema, 'postgresql')}."
            f"{quote_identifier(table, 'postgresql')}"
        )
        try:
            rows = await self._fetch_all(sql, database=database)
        except Exception as exc:  # noqa: BLE001 - a count is best effort
            self._last_error = exc
            return 0
        return int(rows[0][0]) if rows else 0

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        """Describe a table that may live in any user schema of ``database``.

        ``table`` may be schema-qualified (``reporting.hidden_table``) because
        the tree lists non-``public`` objects under that name, or bare like
        ``orders``.

        A bare name is resolved the way the server itself would -- through
        ``search_path`` -- instead of being pinned to ``public``.  Pinning breaks
        tables a connection legitimately reaches via a custom or ``"$user"``
        ``search_path``: with ``search_path = myapp, public`` the statement
        ``select * from "custom_t"`` succeeds while ``"public"."custom_t"``
        errors, so hard-coding ``public`` would report zero columns for a table
        that actually exists.  Only when the name does not resolve through
        ``search_path`` does the lookup fall back to ``public``, which keeps
        describing an unqualified-but-existing ``public`` object the same way
        the tree names it.  The lookup runs on a session bound to ``database``
        for the same reason listings do -- catalogs are per-database.
        """
        info = TableInfo(name=table, database=database)
        info.engine = "PostgreSQL"
        info.charset = "UTF8"
        info.collation = "en_US.UTF-8"

        schema = await self._resolve_schema(database, table)
        relname = _bare_name(table)
        if schema is None:
            # Neither search_path nor ``public`` knows the name.  Return the
            # empty shell rather than guessing a schema: the table may simply
            # not exist, and inventing a schema would hide the real cause.
            return info

        tbl_sql = """
            SELECT c.reltuples::bigint,
                   pg_catalog.obj_description(c.oid, 'pg_class'),
                   COALESCE(am.amname, 'PostgreSQL'),
                   pg_catalog.pg_total_relation_size(c.oid)
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_am am ON am.oid = c.relam
            WHERE n.nspname = $1 AND c.relname = $2
              AND c.relkind IN ('r', 'p', 'v', 'm')
        """
        rows = await self._fetch_all(tbl_sql, (schema, relname), database=database)
        counted = False
        if rows:
            r = rows[0]
            # A never-analyzed table (or a partitioned parent) reports
            # reltuples = -1, which means "unknown", not a negative row count.
            estimate = int(r[0] or 0)
            info.row_count = max(estimate, 0)
            info.comment = r[1] or ""
            info.engine = str(r[2] or "PostgreSQL")
            info.data_length = int(r[3] or 0)
            counted = estimate >= 0

        if not counted:
            # reltuples is only a planner estimate refreshed by ANALYZE/VACUUM,
            # so a freshly loaded table showed 0 rows in the UI even though it
            # held data. Fall back to a real COUNT(*) for the small tables where
            # an exact number matters and the cost is acceptable; the estimate
            # stays the fast path for everything else.
            info.row_count = await self._exact_row_count(database, schema, relname)

        col_sql = """
            SELECT column_name, data_type, is_nullable, column_default,
                   character_maximum_length, numeric_precision, numeric_scale,
                   character_set_name, collation_name, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """
        col_rows = await self._fetch_all(col_sql, (schema, relname), database=database)
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
              AND tc.table_schema = $1 AND tc.table_name = $2
        """
        pk_rows = await self._fetch_all(pk_sql, (schema, relname), database=database)
        pk_set = set(str(r[0]) for r in pk_rows)

        for r in col_rows:
            col_name = r[0]
            info.columns.append(
                ColumnInfo(
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
                    ordinal_position=r[9] or 0,
                    is_auto_increment=(r[3] or "").startswith("nextval("),
                )
            )

        idx_sql = """
            SELECT i.relname, a.attname, ix.indisunique, ix.indisprimary, am.amname
            FROM pg_catalog.pg_class t
            JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_catalog.pg_index ix ON t.oid = ix.indrelid
            JOIN pg_catalog.pg_class i ON ix.indexrelid = i.oid
            LEFT JOIN pg_catalog.pg_am am ON i.relam = am.oid
            CROSS JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS ik(attnum, pos)
            JOIN pg_catalog.pg_attribute a ON a.attrelid = t.oid AND a.attnum = ik.attnum
            WHERE t.relkind IN ('r', 'p') AND n.nspname = $1 AND t.relname = $2
            ORDER BY i.relname, ik.pos
        """
        idx_rows = await self._fetch_all(idx_sql, (schema, relname), database=database)
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

        _fk_map = {
            "a": "NO ACTION",
            "r": "RESTRICT",
            "c": "CASCADE",
            "n": "SET NULL",
            "d": "SET DEFAULT",
        }
        # The referenced table gets its own namespace join: a foreign key may
        # point into another schema, and a bare relname would be ambiguous there.
        fk_sql = """
            SELECT con.conname, a.attname, fr.relname, fn.nspname, fa.attname,
                   con.confdeltype, con.confupdtype
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class t ON con.conrelid = t.oid
            JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_catalog.pg_class fr ON con.confrelid = fr.oid
            JOIN pg_catalog.pg_namespace fn ON fn.oid = fr.relnamespace
            CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ck(attnum, pos)
            JOIN pg_catalog.pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
            CROSS JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS fk(attnum, fpos)
            JOIN pg_catalog.pg_attribute fa ON fa.attrelid = fr.oid AND fa.attnum = fk.attnum
            WHERE con.contype = 'f' AND n.nspname = $1 AND t.relname = $2
              AND ck.pos = fk.fpos
            ORDER BY con.conname, ck.pos
        """
        fk_rows = await self._fetch_all(fk_sql, (schema, relname), database=database)
        for r in fk_rows:
            # confdeltype/confupdtype are PostgreSQL `"char"` columns, which
            # asyncpg hands back as BYTES (b"c"), not str.  str(b"c") is "b'c'",
            # so the map lookup missed every row and a real ON DELETE CASCADE
            # constraint was silently reported as NO ACTION. Normalise the raw
            # value to its single character before the lookup.
            info.foreign_keys.append(
                ForeignKeyInfo(
                    name=r[0],
                    column=r[1],
                    ref_table=_qualified_name(str(r[3]), str(r[2])),
                    ref_column=r[4],
                    on_delete=_fk_map.get(_char_key(r[5]), "NO ACTION"),
                    on_update=_fk_map.get(_char_key(r[6]), "NO ACTION"),
                )
            )

        return info

    # ---- query execution ----

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        """Run a statement, single or multi-statement.

        ``asyncpg`` splits the two paths: ``prepare()`` can only handle ONE
        statement, and rejects a script with *"cannot insert multiple commands
        into a prepared statement"*.  Generated DDL (pg_dump output, schema-sync
        scripts) is inherently multi-statement, and that error made every
        structure copy silently do nothing.  Multi-statement text therefore
        goes through the simple-query protocol (``conn.execute``), which handles
        a script; it cannot return rows, which is correct because a script of
        that shape is DDL/DML only.
        """
        result = QueryResult()
        start = time.perf_counter()
        try:
            async with self._require_pool().acquire() as conn:
                if _looks_multi_statement(sql):
                    tag = await conn.execute(sql)
                    result.affected_rows = _parse_cmd_tag(tag)
                else:
                    stmt = await conn.prepare(sql)
                    attrs = stmt.get_attributes()
                    args = list(params) if params else []

                    if attrs:
                        rows = await stmt.fetch(*args)
                        result.columns = [
                            ColumnMeta(name=a.name, data_type=str(a.type)) for a in attrs
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
        """Run ``sql`` once per parameter tuple and return how many ran.

        ``asyncpg.executemany`` discards the per-statement command tags and
        returns ``None``, so the count reported here is the size of the batch
        that was actually sent -- not a parsed tag, which does not exist.
        """
        if not params_list:
            return 0
        async with self._require_pool().acquire() as conn:
            await conn.executemany(sql, params_list)
        return len(params_list)

    async def fetch_page(
        self,
        database: str,
        table: str,
        offset: int,
        limit: int,
        order_by: str | None = None,
        order_dir: str = "ASC",
    ) -> QueryResult:
        """Read one page of ``table``, which may be ``schema.table``.

        The reference goes through :func:`quote_qualified` so there is one
        naming rule in the codebase: a bare name stays unqualified (and so
        resolves through ``search_path``), a dotted name keeps its schema, and
        ``database`` is ignored -- PostgreSQL rejects cross-database references,
        and hard-coding ``"public"`` here hid every non-public table the tree
        now lists.
        """
        _ = database
        order = f'ORDER BY {quote_identifier(order_by, "postgresql")} {order_dir}' if order_by else ""
        ref = quote_qualified(table, "postgresql")
        sql = f"SELECT * FROM {ref} {order} LIMIT $1 OFFSET $2"
        return await self.execute(sql, (limit, offset))

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        """Insert ``rows`` into ``table`` (possibly ``schema.table``)."""
        if not rows:
            return 0
        columns = list(rows[0].keys())
        placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
        col_names = ", ".join(quote_identifier(c, "postgresql") for c in columns)
        ref = quote_qualified(table, "postgresql")
        sql = f"INSERT INTO {ref} ({col_names}) VALUES ({placeholders})"
        params = [tuple(r[c] for c in columns) for r in rows]
        async with self._require_pool().acquire() as conn:
            await conn.executemany(sql, params)
        return len(rows)

    async def update_row(
        self,
        database: str,
        table: str,
        values: dict,
        where: dict,
    ) -> int:
        """Update rows of ``table`` (possibly ``schema.table``)."""
        _ = database
        n = len(values)
        set_clause = ", ".join(
            f"{quote_identifier(k, 'postgresql')} = ${i + 1}" for i, k in enumerate(values)
        )
        where_clause = " AND ".join(
            f"{quote_identifier(k, 'postgresql')} = ${n + i + 1}" for i, k in enumerate(where)
        )
        ref = quote_qualified(table, "postgresql")
        sql = f"UPDATE {ref} SET {set_clause} WHERE {where_clause}"
        result = await self.execute(sql, tuple(list(values.values()) + list(where.values())))
        return result.affected_rows

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        """Delete rows of ``table`` (possibly ``schema.table``)."""
        _ = database
        where_clause = " AND ".join(
            f"{quote_identifier(k, 'postgresql')} = ${i + 1}" for i, k in enumerate(where)
        )
        ref = quote_qualified(table, "postgresql")
        sql = f"DELETE FROM {ref} WHERE {where_clause}"
        result = await self.execute(sql, tuple(where.values()))
        return result.affected_rows

    # ---- private helpers ----

    def _require_pool(self) -> asyncpg.Pool:
        """Return the open pool or fail with a message a user can act on.

        Every CRUD primitive used to dereference ``self._pool`` directly, so a
        call made before ``connect()`` (or after ``disconnect()``) died with
        ``AttributeError: 'NoneType' object has no attribute 'acquire'``.  One
        guard keeps the failure explicit and type-checks the attribute.
        """
        pool = self._pool
        if pool is None:
            raise RuntimeError("PostgreSQL connection is not open")
        return pool

    async def _resolve_schema(self, database: str, table: str) -> str | None:
        """Schema ``table`` actually resolves to inside ``database``.

        A qualified name carries its own answer.  A bare name is resolved by the
        server through ``search_path`` via ``to_regclass``, which returns NULL
        when nothing matches -- so this asks PostgreSQL rather than reimplementing
        its search order in Python.  ``public`` is only a fallback for a name
        that did not resolve, keeping an unqualified-but-``public`` object
        describable exactly as the tree names it.
        """
        schema = _schema_of(table)
        if schema is not None:
            return schema
        rows = await self._fetch_all(
            "SELECT n.nspname FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.oid = pg_catalog.to_regclass($1)",
            (quote_qualified(table, "postgresql"),),
            database=database,
        )
        if rows:
            return str(rows[0][0])
        return _DEFAULT_SCHEMA

    async def _fetch_all(
        self, sql: str, params: tuple = (), *, database: str | None = None
    ) -> list[asyncpg.Record]:
        """Run a catalog query on the session bound to ``database``."""
        async with self._connection(database) as conn:
            return await conn.fetch(sql, *params)
