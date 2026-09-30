"""Tests for the ClickHouse connector (clickhouse-connect bridged to asyncio).

clickhouse-connect is replaced with a fake so these run without a real server.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from unittest.mock import MagicMock

import pytest

from open_navicat.drivers import clickhouse_connector as mod
from open_navicat.drivers.clickhouse_connector import (
    ClickHouseConnector,
    _bare_type,
    _literal,
    _normalize_value,
    _quote,
    _split_qualified,
)
from open_navicat.errors import DriverNotFoundError
from open_navicat.models import ConnectionInfo


class FakeResultSet:
    def __init__(self, column_names=(), result_rows=()) -> None:
        self.column_names = list(column_names)
        self.result_rows = [list(r) for r in result_rows]


def fake_client(query_result=None, error=None) -> MagicMock:
    client = MagicMock()
    if error is not None:

        def _raise(*a, **k):
            raise error

        client.query.side_effect = _raise
        client.command.side_effect = _raise
    else:
        client.query.return_value = query_result or FakeResultSet()
    client.insert.return_value = MagicMock()
    return client


def info(**overrides) -> ConnectionInfo:
    base = dict(
        engine="clickhouse", host="ch01", port=8123, user="default",
        password="pw", database="analytics",
    )
    base.update(overrides)
    return ConnectionInfo(**base)


def make_connector(client, i=None) -> ClickHouseConnector:
    c = ClickHouseConnector(i or info())
    c._client = client
    return c


class TestNormalization:
    def test_decimal_becomes_float(self) -> None:
        assert _normalize_value(decimal.Decimal("2.5")) == 2.5

    def test_bytes_become_hex(self) -> None:
        assert _normalize_value(b"\x01\x02") == "0102"

    def test_datetime_becomes_iso(self) -> None:
        dt = datetime.datetime(2026, 9, 29, 10, 30)
        assert _normalize_value(dt) == "2026-09-29T10:30:00"

    def test_uuid_becomes_str(self) -> None:
        u = uuid.uuid4()
        assert _normalize_value(u) == str(u)

    def test_lists_are_normalized_recursively(self) -> None:
        assert _normalize_value([decimal.Decimal("1"), b"\xab"]) == [1.0, "ab"]

    def test_plain_values_pass_through(self) -> None:
        assert _normalize_value("x") == "x"
        assert _normalize_value(None) is None
        assert _normalize_value(7) == 7


class TestHelpers:
    def test_bare_type_unwraps_nullable(self) -> None:
        assert _bare_type("Nullable(UInt64)") == "uint64"

    def test_bare_type_unwraps_lowcardinality(self) -> None:
        assert _bare_type("LowCardinality(String)") == "string"

    def test_bare_type_keeps_array(self) -> None:
        assert _bare_type("Array(Int32)") == "array(int32)"

    def test_split_qualified(self) -> None:
        assert _split_qualified("analytics.events", "default") == ("analytics", "events")
        assert _split_qualified("events", "db1") == ("db1", "events")

    def test_quote_escapes_backticks(self) -> None:
        assert _quote("we`ird") == "`we\\`ird`"
        assert _quote(None) == "``"

    def test_literal_renders_types(self) -> None:
        assert _literal(None) == "NULL"
        assert _literal(True) == "true"
        assert _literal(3) == "3"
        assert _literal(decimal.Decimal("1.5")) == "1.5"
        assert _literal("O'Brien") == "'O\\'Brien'"
        assert _literal(datetime.date(2026, 1, 2)) == "'2026-01-02'"
        assert (
            _literal(datetime.datetime(2026, 1, 2, 3, 4, 5)) == "'2026-01-02 03:04:05'"
        )


class TestClientKwargs:
    def test_http_defaults(self) -> None:
        c = ClickHouseConnector(info())
        kw = c._client_kwargs()
        assert kw["host"] == "ch01"
        assert kw["port"] == 8123
        assert "secure" not in kw

    def test_ssl_switches_to_secure(self) -> None:
        c = ClickHouseConnector(info(use_ssl=True, port=0))
        kw = c._client_kwargs()
        assert kw["secure"] is True
        assert kw["port"] == 8443
        assert kw["verify"] is False  # no CA supplied

    def test_ssl_with_ca_verifies(self) -> None:
        c = ClickHouseConnector(info(use_ssl=True, ssl_ca="/x/ca.pem"))
        kw = c._client_kwargs()
        assert kw["verify"] is True
        assert kw["ca_cert"] == "/x/ca.pem"

    def test_query_limit_disabled(self) -> None:
        # Row limits must not silently truncate browse results.
        assert ClickHouseConnector(info())._client_kwargs()["query_limit"] == 0


class TestConnect:
    async def test_connect_without_driver_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(mod, "clickhouse_connect", None)
        with pytest.raises(DriverNotFoundError):
            await ClickHouseConnector(info()).connect()

    async def test_connect_success(self, monkeypatch) -> None:
        client = fake_client()
        fake_mod = MagicMock()
        fake_mod.get_client.return_value = client
        monkeypatch.setattr(mod, "clickhouse_connect", fake_mod)
        c = ClickHouseConnector(info())
        assert await c.connect() is True
        assert await c.is_connected() is True
        await c.disconnect()
        client.close.assert_called_once()

    async def test_connect_failure_records_last_error(self, monkeypatch) -> None:
        boom = OSError("no route to ch01")
        fake_mod = MagicMock()
        fake_mod.get_client.side_effect = boom
        monkeypatch.setattr(mod, "clickhouse_connect", fake_mod)
        c = ClickHouseConnector(info())
        assert await c.connect() is False
        assert c.last_error is boom


class TestQuery:
    async def test_execute_select(self) -> None:
        rs = FakeResultSet(("id", "name"), [(1, "a"), (2, decimal.Decimal("2"))])
        c = make_connector(fake_client(rs))
        result = await c.execute("SELECT id, name FROM t")
        assert result.success is True
        assert [col.name for col in result.columns] == ["id", "name"]
        assert result.rows == [[1, "a"], [2, 2.0]]
        assert result.row_count == 2

    async def test_execute_without_connection(self) -> None:
        c = ClickHouseConnector(info())
        result = await c.execute("SELECT 1")
        assert result.success is False
        assert "not open" in result.error_message

    async def test_execute_error_records_detail(self) -> None:
        c = make_connector(fake_client(error=Exception("Code: 60. UNKNOWN_TABLE")))
        result = await c.execute("SELECT * FROM missing")
        assert result.success is False
        assert "UNKNOWN_TABLE" in result.error_message
        assert c.last_error is not None

    async def test_execute_passes_named_params(self) -> None:
        client = fake_client(FakeResultSet(("n",), [(5,)]))
        c = make_connector(client)
        await c.execute("SELECT count() FROM t WHERE db = %(db)s", {"db": "x"})
        args = client.query.call_args[0]
        assert args[0] == "SELECT count() FROM t WHERE db = %(db)s"
        assert args[1] == {"db": "x"}

    async def test_execute_rejects_positional_params(self) -> None:
        # Params must not be silently dropped — that could change semantics.
        c = make_connector(fake_client())
        result = await c.execute("SELECT * FROM t WHERE id = %s", ("x",))
        assert result.success is False
        assert "named" in result.error_message

    async def test_ping(self) -> None:
        c = make_connector(fake_client(FakeResultSet(("1",), [(1,)])))
        assert await c.ping() is True
        offline = ClickHouseConnector(info())
        assert await offline.ping() is False

    async def test_ping_failure(self) -> None:
        c = make_connector(fake_client(error=Exception("dead")))
        assert await c.ping() is False


class TestMetadata:
    async def test_list_databases(self) -> None:
        rs = FakeResultSet(("name", "engine"), [("default", "Atomic"), ("system", "Atomic")])
        c = make_connector(fake_client(rs))
        dbs = await c.list_databases()
        assert [d.name for d in dbs] == ["default", "system"]

    async def test_list_tables_excludes_views(self) -> None:
        client = fake_client(FakeResultSet(("name",), [("events",)]))
        c = make_connector(client)
        tables = await c.list_tables("analytics")
        assert tables == ["events"]
        sql = client.query.call_args[0][0]
        assert "engine != 'View'" in sql

    async def test_list_views(self) -> None:
        client = fake_client(FakeResultSet(("name",), [("mv_daily",)]))
        c = make_connector(client)
        assert await c.list_views("analytics") == ["mv_daily"]
        sql = client.query.call_args[0][0]
        assert "engine = 'View'" in sql

    async def test_list_routines_empty(self) -> None:
        c = make_connector(fake_client())
        assert await c.list_routines("analytics") == []

    async def test_get_table_info(self) -> None:
        calls = []

        def router(sql, params=None):
            calls.append(sql)
            if "system.tables" in sql and "total_rows" in sql:
                return FakeResultSet(("total_rows",), [(123,)])
            if "system.tables" in sql:
                return FakeResultSet(("engine",), [("MergeTree",)])
            if "system.columns" in sql:
                return FakeResultSet(
                    ("name", "type", "default_kind", "default_expression", "comment"),
                    [
                        ("id", "UInt64", "", "", "pk"),
                        ("name", "Nullable(String)", "DEFAULT", "'x'", ""),
                    ],
                )
            if "system.table_indexes" in sql:
                return FakeResultSet(
                    ("name", "type", "expression"),
                    [("primary", "mergetree", "id")],
                )
            return FakeResultSet()

        client = MagicMock()
        client.query.side_effect = router
        c = make_connector(client)
        info_ = await c.get_table_info("analytics", "events")
        assert info_.engine == "MergeTree"
        assert info_.row_count == 123
        assert info_.columns[0].is_primary_key is True
        assert info_.columns[1].nullable is True
        assert info_.columns[1].default == "DEFAULT 'x'"
        assert info_.columns[1].comment == ""
        assert info_.indexes[0].name == "primary"
        assert info_.indexes[0].columns == ["id"]
        assert info_.foreign_keys == []

    async def test_get_table_info_qualified_name(self) -> None:
        client = MagicMock()
        client.query.return_value = FakeResultSet()
        c = make_connector(client)
        info_ = await c.get_table_info("", "shop.orders")
        assert info_.database == "shop"
        assert info_.name == "orders"


class TestWritePaths:
    async def test_batch_insert(self) -> None:
        client = fake_client()
        c = make_connector(client)
        n = await c.batch_insert(
            "analytics", "events", [{"id": 1, "db": "x"}, {"id": 2, "db": "y"}]
        )
        assert n == 2
        sql, data = client.insert.call_args[0]
        assert "`analytics`.`events`" in sql
        assert data == [[1, "x"], [2, "y"]]

    async def test_batch_insert_failure_returns_zero(self) -> None:
        client = MagicMock()
        client.insert.side_effect = Exception("bad row")
        c = make_connector(client)
        assert await c.batch_insert("db", "t", [{"a": 1}]) == 0
        assert c.last_error is not None

    async def test_execute_many_inserts_rows(self) -> None:
        client = fake_client()
        c = make_connector(client)
        n = await c.execute_many("tbl", [(1,), (2,)])
        assert n == 2
        client.insert.assert_called_once()

    async def test_update_row_uses_mutation(self) -> None:
        client = fake_client()
        c = make_connector(client)
        n = await c.update_row("db", "t", {"name": "o'brien"}, {"id": 7})
        assert n == 1
        sql = client.query.call_args[0][0]
        assert sql.startswith("ALTER TABLE `db`.`t` UPDATE")
        assert "`name` = 'o\\'brien'" in sql
        assert "`id` = 7" in sql

    async def test_delete_row_uses_mutation(self) -> None:
        client = fake_client()
        c = make_connector(client)
        assert await c.delete_row("db", "t", {"id": 1}) == 1
        sql = client.query.call_args[0][0]
        assert sql == "ALTER TABLE `db`.`t` DELETE WHERE `id` = 1"

    async def test_mutation_failure_returns_zero(self) -> None:
        client = fake_client(error=Exception("mutations disabled"))
        c = make_connector(client)
        assert await c.update_row("db", "t", {"a": 1}, {"b": 2}) == 0

    async def test_fetch_page(self) -> None:
        client = fake_client(FakeResultSet(("id",), [(1,)]))
        c = make_connector(client)
        result = await c.fetch_page("db", "t", 10, 5, order_by="id", order_dir="desc")
        assert result.success is True
        sql = client.query.call_args[0][0]
        assert "ORDER BY `id` DESC LIMIT 5 OFFSET 10" in sql

    async def test_fetch_page_without_order(self) -> None:
        client = fake_client()
        c = make_connector(client)
        await c.fetch_page("db", "t", 0, 100)
        sql = client.query.call_args[0][0]
        assert "SELECT * FROM `db`.`t` LIMIT 100 OFFSET 0" in sql
        # Integers are interpolated, never user-controlled strings.
        assert "OFFSET 0" in sql
