"""Tests for the PostgreSQL connector's catalog listings.

Regression cover for the reported bug: expanding a database in the object tree
and opening "Tables" showed a grid with headers and no rows.  The cause was that
the connector ignored its ``database`` argument, only read schema ``public``, and
never overrode ``list_tables_with_info`` (so the grid got the base-class stub's
blank metadata).  ``asyncpg`` is faked here -- a pool whose ``acquire()`` yields a
connection that records the SQL it is handed -- so the suite runs with no server.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Iterator
from unittest.mock import patch

import pytest

from open_navicat.drivers import postgresql_connector as mod
from open_navicat.drivers.postgresql_connector import (
    PostgreSQLConnector,
    _bare_name,
    _qualified_name,
    _schema_of,
)
from open_navicat.models import ConnectionInfo

# ---- fakes -------------------------------------------------------------------


class FakeStatement:
    """Minimal prepared statement: no attributes, so ``execute`` takes the DML path."""

    def get_attributes(self) -> list[Any]:
        return []


class FakeConnection:
    """Minimal ``asyncpg.Connection``: records queries, replays canned rows."""

    def __init__(self, responder: Callable[[str], Any], *, closed: bool = False) -> None:
        self._responder = responder
        self._closed = closed
        #: ``fetch`` calls, i.e. catalog reads.
        self.queries: list[tuple[str, tuple]] = []
        #: ``execute``/``executemany`` calls, i.e. statements that change data.
        self.executed: list[tuple[str, tuple]] = []
        self.close_calls = 0
        self.executed_tag = "INSERT 0 1"

    async def fetch(self, sql: str, *params: object) -> Any:
        self.queries.append((sql, params))
        result = self._responder(sql)
        if isinstance(result, BaseException):
            raise result
        return list(result)

    async def prepare(self, sql: str) -> FakeStatement:
        return FakeStatement()

    async def execute(self, sql: str, *args: object) -> str:
        self.executed.append((sql, args))
        return self.executed_tag

    async def executemany(self, sql: str, args: Any) -> str:
        self.executed.append((sql, tuple(args)))
        return self.executed_tag

    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self.close_calls += 1
        self._closed = True


class _Acquire:
    """Stand-in for ``asyncpg.Pool.acquire()``'s async context manager."""

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class FakePool:
    """Minimal ``asyncpg.Pool`` bound to one database."""

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn
        self.close_calls = 0

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)

    async def close(self) -> None:
        self.close_calls += 1


class FakeAsyncpg:
    """Stand-in for the ``asyncpg`` module: records per-database connections."""

    def __init__(self, responder: Callable[[str], Any]) -> None:
        self._responder = responder
        self.connections: dict[str, FakeConnection] = {}
        self.connect_kwargs: list[dict[str, Any]] = []
        self.connect_error: BaseException | None = None
        #: Databases whose fresh session should start out already closed.
        self.connect_closed = False

    async def connect(self, **kwargs: Any) -> FakeConnection:
        if self.connect_error is not None:
            raise self.connect_error
        self.connect_kwargs.append(dict(kwargs))
        database = str(kwargs["database"])
        # A pre-seeded session stands in for the server's answer for that
        # database, letting a test prove *which* session answered rather than
        # only that some query ran.
        seeded = self.connections.get(database)
        if seeded is not None and not seeded.is_closed():
            return seeded
        conn = FakeConnection(self._responder, closed=self.connect_closed)
        self.connections[database] = conn
        return conn


def responder(rows_by_marker: dict[str, Any]) -> Callable[[str], Any]:
    """Build a SQL router: the first marker contained in the SQL wins.

    Markers are checked in insertion order, so the most specific one is put
    first.  A value may be a list of rows, or an exception to raise.
    """

    def respond(sql: str) -> Any:
        for marker, rows in rows_by_marker.items():
            if marker in sql:
                return rows
        return []

    return respond


#: Distinctive fragments of each catalog statement.  Aliased here so a test
#: fails loudly (empty result) if the statement shape changes unexpectedly.
MARKS = {
    "tables": "WHERE c.relkind IN ('r', 'p')",
    "tables_info": "pg_total_relation_size(c.oid), am.amname",
    "views": "WHERE c.relkind = 'v'",
    "routines": "information_schema.routines",
    "triggers": "pg_catalog.pg_trigger t",
    # Must precede "table_row": the resolver is asked first and returns the
    # schema, so its distinct marker has to win over the generic one.
    "resolve": "c.oid = pg_catalog.to_regclass",
    "table_row": "c.reltuples::bigint",
    "columns": "information_schema.columns",
    "pk": "constraint_type = 'PRIMARY KEY'",
    "indexes": "pg_catalog.pg_index",
    "fks": "con.contype = 'f'",
}


def info(database: str = "postgres", **overrides: Any) -> ConnectionInfo:
    base: dict[str, Any] = {
        "engine": "postgresql",
        "host": "pg01",
        "port": 5432,
        "user": "angel",
        "password": "",
        "database": database,
    }
    base.update(overrides)
    return ConnectionInfo(**base)


def make_connector(
    rows_by_marker: dict[str, Any] | None = None,
    *,
    database: str = "postgres",
) -> tuple[PostgreSQLConnector, FakeAsyncpg, FakePool]:
    """Wire a connector to a fake pool plus a fake ``asyncpg`` module.

    The fake is installed on the module for the duration of the test, exactly as
    the real code would see it: ``_open_database_connection`` reaches for
    ``asyncpg.connect``, and letting that hit the real package would open a
    socket instead of failing loudly.
    """
    fake = FakeAsyncpg(responder(rows_by_marker or {}))
    pool = FakePool(FakeConnection(fake._responder))
    connector = PostgreSQLConnector(info(database=database))
    connector._pool = pool  # type: ignore[assignment]
    # Installed on the module (not just returned) because
    # ``_open_database_connection`` calls ``asyncpg.connect``; the autouse
    # ``_restore_asyncpg`` fixture puts the real module back afterwards.
    mod.asyncpg = fake
    return connector, fake, pool


@pytest.fixture(autouse=True)
def _restore_asyncpg() -> Iterator[None]:
    """Restore the real ``asyncpg`` module after each test.

    ``make_connector`` installs its fake into the module (that is the object
    ``_open_database_connection`` actually calls), so the swap has to be undone
    or the next test would inherit a stale fake.
    """
    original = mod.asyncpg
    try:
        yield
    finally:
        mod.asyncpg = original


# ---- naming contract ---------------------------------------------------------


class TestNaming:
    def test_public_is_bare(self) -> None:
        assert _qualified_name("public", "orders") == "orders"

    def test_other_schema_is_qualified(self) -> None:
        assert _qualified_name("reporting", "hidden_table") == "reporting.hidden_table"

    def test_empty_schema_is_bare(self) -> None:
        assert _qualified_name("", "orders") == "orders"

    def test_bare_name_has_no_schema(self) -> None:
        # None, not "public": a bare name must resolve through search_path,
        # and pinning it to public breaks custom/"$user" search paths.
        assert _schema_of("orders") is None
        assert _bare_name("orders") == "orders"

    def test_qualified_name_splits_on_the_first_dot(self) -> None:
        # A dot inside the table name must stay part of the name; splitting at
        # the last dot would attribute the object to the wrong schema.
        assert _schema_of("reporting.hidden_table") == "reporting"
        assert _bare_name("reporting.hidden_table") == "hidden_table"
        assert _schema_of("public.a.b") == "public"
        assert _bare_name("public.a.b") == "a.b"

    def test_leading_dot_is_treated_as_bare(self) -> None:
        assert _schema_of(".orders") is None
        assert _bare_name(".orders") == "orders"


# ---- cross-database listing --------------------------------------------------


class TestDatabaseRouting:
    async def test_same_database_uses_the_pool(self) -> None:
        connector, fake, pool = make_connector(
            {MARKS["tables"]: [("public", "orders")]}, database="postgres"
        )
        assert await connector.list_tables("postgres") == ["orders"]
        # A pool session is bound to its own database; no extra connection.
        assert fake.connect_kwargs == []
        assert pool._conn.queries  # the pool's session served the query

    async def test_other_database_opens_a_separate_connection(self) -> None:
        connector, fake, pool = make_connector(
            {MARKS["tables"]: [("public", "only_in_alpha")]}, database="postgres"
        )
        assert await connector.list_tables("alpha") == ["only_in_alpha"]
        assert [kw["database"] for kw in fake.connect_kwargs] == ["alpha"]
        # The embedded connection, not the pool, ran the statement.
        assert fake.connections["alpha"].queries
        assert not pool._conn.queries
        kw = fake.connect_kwargs[0]
        assert kw["host"] == "pg01"
        assert kw["port"] == 5432
        assert kw["user"] == "angel"
        assert kw["password"] == ""

    async def test_other_database_connection_is_cached(self) -> None:
        connector, fake, _ = make_connector(
            {MARKS["tables"]: [("public", "t")]}, database="postgres"
        )
        await connector.list_tables("alpha")
        await connector.list_tables("alpha")
        await connector.list_views("alpha")
        # Three listings, one session -- tree expansion must not reconnect.
        assert len(fake.connect_kwargs) == 1
        assert len(fake.connections["alpha"].queries) == 3

    async def test_each_database_gets_its_own_connection(self) -> None:
        connector, fake, _ = make_connector({}, database="postgres")
        await connector.list_tables("alpha")
        await connector.list_tables("beta")
        assert sorted(fake.connections) == ["alpha", "beta"]

    async def test_listing_uses_the_requested_database_every_time(self) -> None:
        # The bug: every tree node returned the pool's own (often empty) list.
        per_db = {
            "alpha": [("public", "only_in_alpha")],
            "beta": [("public", "only_in_beta")],
        }
        connector, fake, _ = make_connector({}, database="postgres")
        # Seed one session per database with its own rows, so the assertion
        # proves the connector selected the right session (not merely that a
        # query ran somewhere).
        for db, rows in per_db.items():
            fake.connections[db] = FakeConnection(lambda sql, r=rows: list(r))

        assert await connector.list_tables("alpha") == ["only_in_alpha"]
        assert await connector.list_tables("beta") == ["only_in_beta"]
        # Each session was asked exactly once, and the pool's was never used.
        assert len(fake.connections["alpha"].queries) == 1
        assert len(fake.connections["beta"].queries) == 1
        assert connector._pool is not None
        assert connector._pool._conn.queries == []  # type: ignore[union-attr]

    async def test_dead_cached_connection_is_replaced(self) -> None:
        connector, fake, _ = make_connector(
            {MARKS["tables"]: [("public", "t")]}, database="postgres"
        )
        await connector.list_tables("alpha")
        fake.connections["alpha"]._closed = True  # e.g. server restart
        assert await connector.list_tables("alpha") == ["t"]
        assert len(fake.connect_kwargs) == 2
        assert fake.connections["alpha"].close_calls == 0


# ---- schema coverage and naming ----------------------------------------------


class TestListTables:
    async def test_naming_contract_in_results(self) -> None:
        connector, _, _ = make_connector(
            {
                MARKS["tables"]: [
                    ("public", "orders"),
                    ("reporting", "hidden_table"),
                ]
            },
            database="postgres",
        )
        assert await connector.list_tables("postgres") == ["orders", "reporting.hidden_table"]

    async def test_system_schemas_are_excluded_in_sql(self) -> None:
        connector, _, _ = make_connector({MARKS["tables"]: []}, database="postgres")
        await connector.list_tables("postgres")
        sql = connector._pool._conn.queries[0][0]  # type: ignore[union-attr]
        assert "n.nspname !~ '^pg_'" in sql
        assert "n.nspname <> 'information_schema'" in sql
        # Hard-coding table_schema = 'public' is exactly the bug being fixed.
        assert "table_schema = 'public'" not in sql

    async def test_failure_returns_empty_but_records_the_cause(self, caplog: Any) -> None:
        connector, _, _ = make_connector(
            {MARKS["tables"]: RuntimeError("permission denied")}, database="postgres"
        )
        with caplog.at_level(logging.WARNING, logger="opennavicat.postgresql"):
            assert await connector.list_tables("postgres") == []
        # An empty list is the connector contract, but silent is not: the cause
        # must be readable through last_error and the log.
        assert isinstance(connector.last_error, RuntimeError)
        assert "permission denied" in str(connector.last_error)
        assert "permission denied" in caplog.text

    async def test_other_database_failure_is_recorded(self) -> None:
        connector, fake, _ = make_connector({}, database="postgres")
        fake.connect_error = OSError("could not connect to server")
        assert await connector.list_tables("alpha") == []
        assert "could not connect" in str(connector.last_error)


class TestListViews:
    async def test_naming_and_exclusions(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["views"]: [("public", "v1"), ("reporting", "hidden_view")]},
            database="postgres",
        )
        assert await connector.list_views("postgres") == ["v1", "reporting.hidden_view"]
        sql = connector._pool._conn.queries[0][0]  # type: ignore[union-attr]
        assert "n.nspname !~ '^pg_'" in sql

    async def test_failure_returns_empty_but_records_the_cause(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["views"]: RuntimeError("boom")}, database="postgres"
        )
        assert await connector.list_views("postgres") == []
        assert isinstance(connector.last_error, RuntimeError)


class TestListRoutines:
    async def test_overloads_collapse_to_a_callable_name(self) -> None:
        connector, _, _ = make_connector(
            {
                MARKS["routines"]: [
                    # specific_name carries an OID suffix nobody can call or drop.
                    ("public", "noop_fn", "FUNCTION"),
                    ("public", "noop_fn", "FUNCTION"),
                    ("reporting", "audit_fn", "FUNCTION"),
                ]
            },
            database="postgres",
        )
        assert await connector.list_routines("postgres") == [
            ("noop_fn", "FUNCTION"),
            ("reporting.audit_fn", "FUNCTION"),
        ]

    async def test_specific_name_is_not_requested(self) -> None:
        connector, _, _ = make_connector({MARKS["routines"]: []}, database="postgres")
        await connector.list_routines("postgres")
        sql = connector._pool._conn.queries[0][0]  # type: ignore[union-attr]
        assert "specific_name" not in sql
        assert "routine_schema !~ '^pg_'" in sql

    async def test_failure_returns_empty_but_records_the_cause(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["routines"]: RuntimeError("boom")}, database="postgres"
        )
        assert await connector.list_routines("postgres") == []
        assert isinstance(connector.last_error, RuntimeError)


class TestListTriggers:
    async def test_trigger_pairs_follow_the_naming_contract(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["triggers"]: [("public", "orders", "trig_a"), ("reporting", "hidden", "trig_b")]},
            database="postgres",
        )
        assert await connector.list_triggers("postgres") == [
            ("trig_a", "orders"),
            ("trig_b", "reporting.hidden"),
        ]

    async def test_internal_triggers_are_excluded_and_systems_filtered(self) -> None:
        connector, _, _ = make_connector({MARKS["triggers"]: []}, database="postgres")
        await connector.list_triggers("postgres")
        sql = connector._pool._conn.queries[0][0]  # type: ignore[union-attr]
        assert "NOT t.tgisinternal" in sql
        assert "n.nspname !~ '^pg_'" in sql

    async def test_failure_returns_empty_but_records_the_cause(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["triggers"]: RuntimeError("boom")}, database="postgres"
        )
        assert await connector.list_triggers("postgres") == []
        assert isinstance(connector.last_error, RuntimeError)


# ---- table list metadata -----------------------------------------------------


class TestListTablesWithInfo:
    async def test_metadata_matches_the_grid_contract(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["tables_info"]: [("public", "orders", 16384, "heap")]},
            database="postgres",
        )
        rows = await connector.list_tables_with_info("postgres")
        assert rows == [
            {
                "name": "orders",
                "auto_increment": None,
                "update_time": "",
                "data_length": 16384,
                "engine": "heap",
            }
        ]

    async def test_non_public_schema_is_qualified(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["tables_info"]: [("reporting", "hidden_table", 8192, "heap")]},
            database="postgres",
        )
        rows = await connector.list_tables_with_info("postgres")
        assert [r["name"] for r in rows] == ["reporting.hidden_table"]

    async def test_unknown_access_method_falls_back_to_the_engine_name(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["tables_info"]: [("public", "foreign_tbl", 0, None)]},
            database="postgres",
        )
        rows = await connector.list_tables_with_info("postgres")
        assert rows[0]["engine"] == "PostgreSQL"
        assert rows[0]["data_length"] == 0

    async def test_sql_counts_partitions_and_queries_the_access_method(self) -> None:
        connector, _, _ = make_connector({MARKS["tables_info"]: []}, database="postgres")
        await connector.list_tables_with_info("postgres")
        sql = connector._pool._conn.queries[0][0]  # type: ignore[union-attr]
        # pg_total_relation_size on the parent already includes its partitions;
        # zeroing it out for relkind 'p' would report an empty partitioned table.
        assert "CASE WHEN c.relkind = 'p'" not in sql
        assert "pg_total_relation_size(c.oid)" in sql
        assert "pg_catalog.pg_am" in sql
        assert "n.nspname !~ '^pg_'" in sql

    async def test_honours_a_sibling_database(self) -> None:
        connector, fake, _ = make_connector(
            {MARKS["tables_info"]: [("public", "only_in_beta", 0, "heap")]},
            database="postgres",
        )
        rows = await connector.list_tables_with_info("beta")
        assert [r["name"] for r in rows] == ["only_in_beta"]
        assert [kw["database"] for kw in fake.connect_kwargs] == ["beta"]

    async def test_failure_returns_empty_but_records_the_cause(self) -> None:
        connector, _, _ = make_connector(
            {MARKS["tables_info"]: RuntimeError("boom")}, database="postgres"
        )
        assert await connector.list_tables_with_info("postgres") == []
        assert isinstance(connector.last_error, RuntimeError)


# ---- get_table_info ----------------------------------------------------------


FULL_ROWS = {
    MARKS["resolve"]: [("reporting",)],
    MARKS["table_row"]: [(-1, "a comment", "heap", 16384)],
    MARKS["columns"]: [
        ("id", "bigint", "NO", "nextval('hidden_table_id_seq'::regclass)", None, None, None, None, None, 1),
        ("name", "text", "YES", None, None, None, None, None, None, 2),
    ],
    MARKS["pk"]: [("id",)],
    MARKS["indexes"]: [
        ("hidden_table_pkey", "id", True, True, "btree"),
        ("hidden_table_name_idx", "name", False, False, "btree"),
    ],
    MARKS["fks"]: [
        ("hidden_table_other_id_fkey", "other_id", "other_table", "reporting", "id", "a", "a"),
    ],
}


class TestGetTableInfo:
    async def test_qualified_name_skips_the_search_path_lookup(self) -> None:
        connector, _, _ = make_connector(FULL_ROWS, database="postgres")
        await connector.get_table_info("postgres", "reporting.hidden_table")
        # The schema is in the name, so no to_regclass round-trip is needed.
        first_sql, first_params = connector._pool._conn.queries[0]  # type: ignore[union-attr]
        assert "to_regclass" not in first_sql
        assert first_params == ("reporting", "hidden_table")

    async def test_every_statement_uses_the_qualified_schema(self) -> None:
        connector, _, _ = make_connector(FULL_ROWS, database="postgres")
        await connector.get_table_info("postgres", "reporting.hidden_table")
        for _sql, params in connector._pool._conn.queries:  # type: ignore[union-attr]
            if params:
                assert params[0] == "reporting"

    async def test_bare_name_resolves_through_search_path(self) -> None:
        # Revision 2 of the contract: a bare name must be resolved the way the
        # server resolves it.  With search_path = myapp, public a bare table
        # exists only in myapp, so pinning public would report zero columns.
        rows = dict(FULL_ROWS)
        rows[MARKS["resolve"]] = [("myapp",)]
        connector, _, _ = make_connector(rows, database="postgres")
        info = await connector.get_table_info("postgres", "custom_t")
        assert [c.name for c in info.columns] == ["id", "name"]
        resolve_sql, resolve_params = connector._pool._conn.queries[0]  # type: ignore[union-attr]
        assert "to_regclass" in resolve_sql
        # The unqualified quoted name is what search_path resolution needs.
        assert resolve_params == ('"custom_t"',)
        for _sql, params in connector._pool._conn.queries[1:]:  # type: ignore[union-attr]
            if params:
                assert params[0] == "myapp"

    async def test_bare_name_falls_back_to_public_when_unresolved(self) -> None:
        # An unqualified name that search_path cannot resolve is still looked
        # up in public, so an existing public object stays describable.
        rows = dict(FULL_ROWS)
        rows[MARKS["resolve"]] = []
        connector, _, _ = make_connector(rows, database="postgres")
        await connector.get_table_info("postgres", "orders")
        first_params = connector._pool._conn.queries[0][1]  # type: ignore[union-attr]
        assert first_params == ('"orders"',)
        second_params = connector._pool._conn.queries[1][1]  # type: ignore[union-attr]
        assert second_params == ("public", "orders")

    async def test_no_hard_coded_public_schema(self) -> None:
        connector, _, _ = make_connector(FULL_ROWS, database="postgres")
        await connector.get_table_info("postgres", "reporting.hidden_table")
        for sql, _params in connector._pool._conn.queries:  # type: ignore[union-attr]
            assert "table_schema = 'public'" not in sql
            assert "n.nspname = 'public'" not in sql

    async def test_metadata_is_populated(self) -> None:
        connector, _, _ = make_connector(FULL_ROWS, database="postgres")
        info = await connector.get_table_info("postgres", "reporting.hidden_table")
        assert info.name == "reporting.hidden_table"
        assert info.database == "postgres"
        assert info.engine == "heap"
        assert info.data_length == 16384
        assert info.comment == "a comment"
        # reltuples = -1 means "never analyzed", not a negative row count.
        assert info.row_count == 0

    async def test_columns_indexes_and_foreign_keys(self) -> None:
        connector, _, _ = make_connector(FULL_ROWS, database="postgres")
        info = await connector.get_table_info("postgres", "reporting.hidden_table")
        assert [(c.name, c.is_primary_key, c.ordinal_position) for c in info.columns] == [
            ("id", True, 1),
            ("name", False, 2),
        ]
        assert info.columns[0].is_auto_increment is True
        assert [i.name for i in info.indexes] == [
            "hidden_table_pkey",
            "hidden_table_name_idx",
        ]
        assert info.indexes[0].is_primary is True
        assert info.indexes[1].columns == ["name"]
        # A qualified foreign-key target keeps the naming contract, otherwise a
        # reference into another schema would look like a public table.
        assert [
            (fk.column, fk.ref_table, fk.ref_column) for fk in info.foreign_keys
        ] == [("other_id", "reporting.other_table", "id")]

    async def test_unknown_table_returns_an_empty_shell(self) -> None:
        connector, _, _ = make_connector({}, database="postgres")
        info = await connector.get_table_info("postgres", "nope")
        assert info.columns == []
        assert info.engine == "PostgreSQL"

    async def test_reads_a_sibling_database(self) -> None:
        connector, fake, _ = make_connector(FULL_ROWS, database="postgres")
        info = await connector.get_table_info("beta", "only_in_beta")
        assert info.database == "beta"
        assert [kw["database"] for kw in fake.connect_kwargs] == ["beta"]
        # Columns came from beta's session, not the pool's.
        assert fake.connections["beta"].queries
        assert not connector._pool._conn.queries  # type: ignore[union-attr]

    async def test_raises_when_the_pool_is_gone(self) -> None:
        connector, _, _ = make_connector({}, database="postgres")
        connector._pool = None
        with pytest.raises(RuntimeError, match="not open"):
            await connector.get_table_info("postgres", "orders")


# ---- lifecycle ---------------------------------------------------------------


class TestLifecycle:
    async def test_disconnect_closes_pool_and_sibling_connections(self) -> None:
        connector, fake, pool = make_connector(
            {MARKS["tables"]: [("public", "t")]}, database="postgres"
        )
        await connector.list_tables("alpha")
        await connector.list_tables("beta")
        assert sorted(connector._database_links) == ["alpha", "beta"]
        await connector.disconnect()
        assert connector._database_links == {}
        assert connector._pool is None
        assert pool.close_calls == 1
        assert fake.connections["alpha"].close_calls == 1
        assert fake.connections["beta"].close_calls == 1

    async def test_disconnect_survives_a_session_that_will_not_close(
        self, caplog: Any
    ) -> None:
        connector, fake, pool = make_connector({}, database="postgres")
        await connector.list_tables("alpha")
        conn = fake.connections["alpha"]

        async def _boom() -> None:
            raise OSError("connection already terminated")

        conn.close = _boom  # type: ignore[method-assign]
        with caplog.at_level(logging.WARNING, logger="opennavicat.postgresql"):
            await connector.disconnect()
        # Cleanup must still finish: the pool is gone and the cache cleared.
        assert connector._pool is None
        assert connector._database_links == {}
        assert pool.close_calls == 1
        assert "already terminated" in caplog.text

    async def test_connect_closes_stale_sibling_links(self) -> None:
        connector, fake, _ = make_connector({}, database="postgres")
        await connector.list_tables("alpha")
        stale = fake.connections["alpha"]
        connector._pool = None  # simulate a prior disconnect-less reconnect
        await connector.connect()
        assert connector._database_links == {}
        assert stale.close_calls == 1

    async def test_connect_forwards_the_saved_connection_info(self) -> None:
        created: list[dict[str, Any]] = []

        async def create_pool(**kwargs: Any) -> FakePool:
            created.append(kwargs)
            return FakePool(FakeConnection(lambda _sql: []))

        connector, fake, _ = make_connector({}, database="alpha")
        with patch.object(mod, "asyncpg") as patched:
            patched.create_pool = create_pool
            assert await connector.connect() is True
        assert created[0]["database"] == "alpha"
        assert created[0]["host"] == "pg01"
        assert created[0]["port"] == 5432
        assert created[0]["user"] == "angel"


# ---- unchanged behaviour -----------------------------------------------------


class TestCrudPrimitives:
    """The CRUD primitives must address the table the tree actually lists.

    They hard-coded ``"public"."{table}"``, so a ``schema.table`` name (which
    the tree now produces for non-public schemas) became
    ``"public"."reporting.hidden_table"`` -- a relation that cannot exist -- and
    a bare name was pinned to ``public``, breaking custom search paths.  They
    now share :func:`quote_qualified`'s one naming rule.
    """

    async def test_fetch_page_bare_name_stays_unqualified(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        await connector.fetch_page("postgres", "orders", 0, 10)
        sql, args = pool._conn.executed[0]
        # Unqualified, so it resolves through search_path like the server would.
        assert sql.startswith('SELECT * FROM "orders"')
        assert '"public".' not in sql
        assert args == (10, 0)

    async def test_fetch_page_qualified_name_keeps_its_schema(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        await connector.fetch_page("postgres", "reporting.hidden_table", 0, 10)
        sql, _args = pool._conn.executed[0]
        assert 'FROM "reporting"."hidden_table"' in sql
        assert '"public".' not in sql

    async def test_fetch_page_orders_by_a_quoted_column(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        await connector.fetch_page(
            "postgres", "reporting.hidden_table", 5, 20, order_by="name", order_dir="DESC"
        )
        sql, args = pool._conn.executed[0]
        assert 'ORDER BY "name" DESC' in sql
        assert args == (20, 5)

    async def test_batch_insert_bare_name(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        assert await connector.batch_insert("postgres", "orders", [{"a": 1, "b": "x"}]) == 1
        sql, args = pool._conn.executed[0]
        assert sql.startswith('INSERT INTO "orders" ("a", "b") VALUES ($1, $2)')
        assert '"public".' not in sql
        assert args == ((1, "x"),)

    async def test_batch_insert_qualified_name(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        assert (
            await connector.batch_insert("postgres", "reporting.hidden_table", [{"id": 7}]) == 1
        )
        sql, _args = pool._conn.executed[0]
        assert 'INSERT INTO "reporting"."hidden_table"' in sql
        assert '"public".' not in sql

    async def test_batch_insert_with_no_rows_issues_no_statement(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        assert await connector.batch_insert("postgres", "reporting.hidden_table", []) == 0
        assert pool._conn.executed == []

    async def test_update_row_bare_name(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        pool._conn.executed_tag = "UPDATE 1"
        affected = await connector.update_row("postgres", "orders", {"name": "o'brien"}, {"id": 3})
        sql, args = pool._conn.executed[0]
        assert sql.startswith('UPDATE "orders" SET "name" = $1 WHERE "id" = $2')
        assert args == ("o'brien", 3)
        assert affected == 1

    async def test_update_row_qualified_name(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        await connector.update_row("postgres", "reporting.hidden_table", {"name": "x"}, {"id": 3})
        sql, _args = pool._conn.executed[0]
        assert sql.startswith('UPDATE "reporting"."hidden_table" SET')
        assert '"public".' not in sql

    async def test_delete_row_bare_name(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        pool._conn.executed_tag = "DELETE 2"
        affected = await connector.delete_row("postgres", "orders", {"id": 3})
        sql, args = pool._conn.executed[0]
        assert sql == 'DELETE FROM "orders" WHERE "id" = $1'
        assert args == (3,)
        assert affected == 2

    async def test_delete_row_qualified_name(self) -> None:
        connector, _, pool = make_connector({}, database="postgres")
        await connector.delete_row("postgres", "reporting.hidden_table", {"id": 3})
        sql, _args = pool._conn.executed[0]
        assert sql == 'DELETE FROM "reporting"."hidden_table" WHERE "id" = $1'
        assert '"public".' not in sql

    async def test_identifiers_with_quotes_are_escaped(self) -> None:
        # Doubling is the standard escape; concatenating raw names let a
        # table called ``we"ird`` break (or inject into) the statement.
        connector, _, pool = make_connector({}, database="postgres")
        await connector.fetch_page("postgres", 'we"ird', 0, 1)
        sql, _args = pool._conn.executed[0]
        assert 'FROM "we""ird"' in sql

    async def test_crud_without_a_pool_raises_instead_of_crashing(self) -> None:
        connector, _, _ = make_connector({}, database="postgres")
        connector._pool = None
        # ``execute`` reports failures through the result, not by raising.
        result = await connector.fetch_page("postgres", "orders", 0, 1)
        assert result.success is False
        assert "not open" in (result.error_message or "")
        # ``batch_insert`` bypasses ``execute`` and so surfaces the error.
        with pytest.raises(RuntimeError, match="not open"):
            await connector.batch_insert("postgres", "orders", [{"a": 1}])


class TestUnchangedBehaviour:
    async def test_list_databases_reads_the_pool(self) -> None:
        connector, fake, pool = make_connector(
            {"FROM pg_database": [("alpha", "UTF8", "en_US.UTF-8")]}, database="postgres"
        )
        dbs = await connector.list_databases()
        assert [d.name for d in dbs] == ["alpha"]
        assert fake.connect_kwargs == []
        assert pool._conn.queries

    async def test_listing_without_a_pool_does_not_raise(self) -> None:
        connector, fake, _ = make_connector({}, database="postgres")
        connector._pool = None
        assert await connector.list_tables("postgres") == []
        assert isinstance(connector.last_error, RuntimeError)
        assert await connector.is_connected() is False
        assert await connector.ping() is False


# ---- helpers still behave ----------------------------------------------------


class TestAsyncApiSurface:
    def test_sibling_connections_are_awaitable_per_database(self) -> None:
        # Guards against an accidental blocking call in the connection cache.
        connector, fake, _ = make_connector({}, database="postgres")

        async def run() -> Any:
            return await connector._database_connection("alpha")

        assert asyncio.iscoroutinefunction(connector._open_database_connection)
        assert asyncio.iscoroutinefunction(connector._database_connection)
        assert asyncio.run(run()) is not None
