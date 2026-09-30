"""Tests for the Oracle connector (python-oracledb bridged to asyncio).

oracledb is replaced with a fake so these run without a real database.
"""

from __future__ import annotations

import datetime
import decimal
from unittest.mock import MagicMock

import pytest

from open_navicat.drivers import oracle_connector as mod
from open_navicat.drivers.oracle_connector import (
    OracleConnector,
    _is_lob,
    _normalize_value,
    _quote,
    _split_qualified,
)
from open_navicat.errors import DriverNotFoundError
from open_navicat.models import ConnectionInfo


class FakeClob:
    """Stand-in for ``oracledb.Clob`` — must be read while the conn is open."""

    def __init__(self, payload) -> None:
        self._payload = payload

    def read(self):
        return self._payload


class FakeBlob(FakeClob):
    pass


@pytest.fixture
def fake_oracledb(monkeypatch) -> MagicMock:
    fake = MagicMock()
    fake.makedsn.side_effect = lambda host, port, service_name=None: (
        f"{host}:{port}/{service_name}" if service_name else f"{host}:{port}"
    )
    # isinstance() in the connector needs real classes for the LOB checks.
    fake.DbLob = FakeClob
    fake.Clob = FakeClob
    fake.Blob = FakeBlob
    monkeypatch.setattr(mod, "oracledb", fake)
    return fake


def make_cursor(description=None, rows=(), rowcount=-1, error=None) -> MagicMock:
    cursor = MagicMock()
    cursor.description = description
    cursor.fetchall.return_value = list(rows)
    cursor.rowcount = rowcount
    if error is not None:
        cursor.execute.side_effect = error
    return cursor


def connected(fake: MagicMock, cursor: MagicMock, **overrides) -> OracleConnector:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    fake.connect.return_value = conn
    c = OracleConnector(info(**overrides))
    c._conn = conn
    return c


def info(**overrides) -> ConnectionInfo:
    base = dict(
        engine="oracle", host="db01", port=1521, user="hr",
        password="pw", database="ORCLPDB1",
    )
    base.update(overrides)
    return ConnectionInfo(**base)


class TestHelpers:
    def test_split_qualified_uppercases(self) -> None:
        assert _split_qualified("hr.employees", "DEFAULT") == ("HR", "EMPLOYEES")
        assert _split_qualified("employees", "HR") == ("HR", "EMPLOYEES")

    def test_quote_doubles_quotes(self) -> None:
        assert _quote('we"ird') == '"we""ird"'

    def test_normalize_decimal(self) -> None:
        assert _normalize_value(decimal.Decimal("9.9")) == 9.9

    def test_normalize_datetime(self) -> None:
        assert (
            _normalize_value(datetime.datetime(2026, 9, 29, 1, 2, 3))
            == "2026-09-29T01:02:03"
        )

    def test_normalize_bytes(self) -> None:
        assert _normalize_value(b"\xde\xad") == "dead"

    def test_lob_read(self, fake_oracledb) -> None:
        assert _normalize_value(FakeClob("text")) == "text"

    def test_lob_unreadable(self, fake_oracledb) -> None:
        class Boom(FakeClob):
            def read(self):
                raise RuntimeError("stream closed")

        assert _is_lob(Boom("x")) is True
        assert _normalize_value(Boom("x")) is None

    def test_is_lob_without_driver(self, monkeypatch) -> None:
        monkeypatch.setattr(mod, "oracledb", None)
        assert _is_lob(object()) is False


class TestConnect:
    async def test_missing_driver_raises(self, monkeypatch) -> None:
        monkeypatch.setattr(mod, "oracledb", None)
        with pytest.raises(DriverNotFoundError):
            await OracleConnector(info()).connect()

    async def test_connect_builds_service_dsn(self, fake_oracledb) -> None:
        c = OracleConnector(info())
        assert await c.connect() is True
        kwargs = fake_oracledb.connect.call_args[1]
        assert kwargs["user"] == "hr"
        assert kwargs["dsn"] == "db01:1521/ORCLPDB1"
        assert kwargs["tcp_connect_timeout"] == 10000
        assert await c.is_connected() is True

    async def test_connect_without_service_uses_host_port(self, fake_oracledb) -> None:
        c = OracleConnector(info(database=""))
        assert await c.connect() is True
        assert fake_oracledb.connect.call_args[1]["dsn"] == "db01:1521"

    async def test_connect_failure_records_error(self, fake_oracledb) -> None:
        boom = Exception("ORA-12541: no listener")
        fake_oracledb.connect.side_effect = boom
        c = OracleConnector(info())
        assert await c.connect() is False
        assert c.last_error is boom
        assert await c.is_connected() is False

    async def test_disconnect_closes(self, fake_oracledb) -> None:
        c = OracleConnector(info())
        assert await c.connect() is True
        conn = fake_oracledb.connect.return_value
        await c.disconnect()
        conn.close.assert_called_once()
        assert await c.is_connected() is False


class TestQuery:
    async def test_execute_select(self, fake_oracledb) -> None:
        cursor = make_cursor(
            description=[("ID", 9, 10, None, None, None, None),
                         ("NAME", 1, 20, None, None, None, None)],
            rows=[(1, "a"), (2, decimal.Decimal("3"))],
        )
        c = connected(fake_oracledb, cursor)
        result = await c.execute("SELECT id, name FROM employees")
        assert result.success is True
        assert [col.name for col in result.columns] == ["ID", "NAME"]
        assert result.rows == [[1, "a"], [2, 3.0]]
        cursor.close.assert_called_once()

    async def test_execute_dml_counts_rows(self, fake_oracledb) -> None:
        cursor = make_cursor(description=None, rowcount=4)
        c = connected(fake_oracledb, cursor)
        result = await c.execute("UPDATE t SET a = 1")
        assert result.affected_rows == 4
        assert result.rows == []

    async def test_execute_without_connection(self) -> None:
        c = OracleConnector(info())
        result = await c.execute("SELECT 1 FROM DUAL")
        assert result.success is False
        assert "not open" in result.error_message

    async def test_execute_failure_records_error(self, fake_oracledb) -> None:
        boom = Exception("ORA-00942: table or view does not exist")
        c = connected(fake_oracledb, make_cursor(error=boom))
        result = await c.execute("SELECT * FROM nope")
        assert result.success is False
        assert "ORA-00942" in result.error_message
        assert c.last_error is boom

    async def test_execute_named_bind(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("N", "NUMBER")], rows=[(1,)])
        c = connected(fake_oracledb, cursor)
        await c.execute("SELECT 1 FROM DUAL WHERE x = :x", {"x": 5})
        cursor.execute.assert_called_once_with("SELECT 1 FROM DUAL WHERE x = :x", {"x": 5})

    async def test_lob_read_on_execute(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("BIO", "CLOB")], rows=[(FakeClob("resume"),)])
        c = connected(fake_oracledb, cursor)
        result = await c.execute("SELECT bio FROM employees")
        assert result.rows == [["resume"]]

    async def test_ping(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("1", "NUMBER")], rows=[(1,)])
        c = connected(fake_oracledb, cursor)
        assert await c.ping() is True
        assert await OracleConnector(info()).ping() is False

    async def test_ping_failure(self, fake_oracledb) -> None:
        c = connected(fake_oracledb, make_cursor(error=Exception("gone")))
        assert await c.ping() is False


class TestMetadata:
    async def test_list_databases_uses_all_users(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("USERNAME",)], rows=[("HR",), ("SYS",)])
        c = connected(fake_oracledb, cursor)
        dbs = await c.list_databases()
        assert [d.name for d in dbs] == ["HR", "SYS"]
        assert "all_users" in cursor.execute.call_args[0][0]

    async def test_list_tables_binds_owner(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("T",)], rows=[("EMPLOYEES",)])
        c = connected(fake_oracledb, cursor)
        assert await c.list_tables("HR") == ["EMPLOYEES"]
        sql, params = cursor.execute.call_args[0]
        assert "all_tables" in sql
        assert params == ("HR",)

    async def test_list_tables_defaults_to_user_schema(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("T",)], rows=[])
        c = connected(fake_oracledb, cursor)
        await c.list_tables("")
        assert cursor.execute.call_args[0][1] == ("HR",)

    async def test_list_views(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("V",)], rows=[("V_STAFF",)])
        c = connected(fake_oracledb, cursor)
        assert await c.list_views("HR") == ["V_STAFF"]

    async def test_list_routines(self, fake_oracledb) -> None:
        cursor = make_cursor(
            description=[("N", "T")],
            rows=[("ADD_JOB", "PROCEDURE"), ("JOBS_PKG", "PACKAGE")],
        )
        c = connected(fake_oracledb, cursor)
        assert await c.list_routines("HR") == [
            ("ADD_JOB", "PROCEDURE"),
            ("JOBS_PKG", "PACKAGE"),
        ]

    async def test_get_table_info(self, fake_oracledb) -> None:
        cursor = MagicMock()
        cursor.execute.return_value = None

        def fetchall():
            sql = cursor.execute.call_args[0][0]
            if "all_tab_comments" in sql:
                return [("employee table", "2026-09-01")]
            if "all_tab_cols" in sql:
                return [
                    (1, "NUMBER", None, 10, 0, "N", None, None, "EMPLOYEE_ID"),
                    (2, "VARCHAR2", 40, None, None, "Y", None, "C", "LAST_NAME"),
                    (None, "SYS_TYPE", 0, None, None, "Y", None, None, "HIDDEN"),
                ]
            if "all_constraints" in sql and "constraint_type = 'P'" in sql:
                return [("EMPLOYEE_ID",)]
            # 'all_indexes' also contains 'all_ind_columns'; keep this branch
            # ahead of any looser all_constraints match.
            if "all_indexes" in sql:
                return [("EMP_IX", "NONUNIQUE", "NORMAL", "LAST_NAME")]
            if "all_constraints" in sql and "constraint_type = 'R'" in sql:
                return [
                    ("FK_DEPT", "DEPARTMENT_ID", "HR.DEPARTMENTS", "DEPARTMENT_ID", "CASCADE")
                ]
            if "COUNT(*)" in sql:
                return [(77,)]
            return []

        cursor.fetchall.side_effect = fetchall
        c = connected(fake_oracledb, cursor)
        info_ = await c.get_table_info("HR", "employees")

        assert info_.name == "EMPLOYEES"
        assert info_.database == "HR"
        assert info_.comment == "employee table"
        assert info_.row_count == 77
        visible = [col for col in info_.columns if col.name != "HIDDEN"]
        assert [col.name for col in visible] == ["EMPLOYEE_ID", "LAST_NAME"]
        assert visible[0].is_primary_key is True
        assert visible[0].nullable is False
        assert visible[0].numeric_precision == 10
        assert visible[1].nullable is True
        assert visible[1].char_max_length == 40
        assert info_.indexes[0].name == "EMP_IX"
        assert info_.indexes[0].columns == ["LAST_NAME"]
        assert info_.indexes[0].is_unique is False
        assert info_.foreign_keys[0].column == "DEPARTMENT_ID"
        assert info_.foreign_keys[0].ref_table == "HR.DEPARTMENTS"
        assert info_.foreign_keys[0].on_delete == "CASCADE"

    async def test_get_table_info_skips_hidden_columns(self, fake_oracledb) -> None:
        cursor = MagicMock()
        cursor.execute.return_value = None

        def fetchall():
            sql = cursor.execute.call_args[0][0]
            if "all_tab_cols" in sql:
                return [(None, "COLLECTION", 0, None, None, "Y", None, None, "SYS_TYPE")]
            return []

        cursor.fetchall.side_effect = fetchall
        c = connected(fake_oracledb, cursor)
        info_ = await c.get_table_info("HR", "t")
        assert info_.columns == []


class TestWritePaths:
    async def test_execute_many(self, fake_oracledb) -> None:
        cursor = make_cursor(rowcount=2)
        c = connected(fake_oracledb, cursor)
        n = await c.execute_many("INSERT INTO t VALUES (:1, :2)", [(1, "a"), (2, "b")])
        assert n == 2
        cursor.executemany.assert_called_once()

    async def test_batch_insert_builds_binds(self, fake_oracledb) -> None:
        cursor = make_cursor(rowcount=2)
        c = connected(fake_oracledb, cursor)
        n = await c.batch_insert("HR", "jobs", [{"job_id": 1}, {"job_id": 2}])
        assert n == 2
        sql, params = cursor.executemany.call_args[0]
        assert sql == 'INSERT INTO "HR"."JOBS" ("job_id") VALUES (:1)'
        assert list(params) == [(1,), (2,)]

    async def test_update_row_positional_binds(self, fake_oracledb) -> None:
        cursor = make_cursor(description=None, rowcount=1)
        c = connected(fake_oracledb, cursor)
        n = await c.update_row("HR", "jobs", {"a": 1}, {"b": 2})
        assert n == 1
        sql, params = cursor.execute.call_args[0]
        assert sql == 'UPDATE "HR"."JOBS" SET "a" = :1 WHERE "b" = :2'
        assert params == (1, 2)

    async def test_delete_row(self, fake_oracledb) -> None:
        cursor = make_cursor(description=None, rowcount=1)
        c = connected(fake_oracledb, cursor)
        n = await c.delete_row("HR", "jobs", {"a": 1, "b": 2})
        assert n == 1
        sql, params = cursor.execute.call_args[0]
        assert sql == 'DELETE FROM "HR"."JOBS" WHERE "a" = :1 AND "b" = :2'
        assert params == (1, 2)

    async def test_fetch_page_uses_named_offsets(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("ID", "NUMBER")], rows=[(1,)])
        c = connected(fake_oracledb, cursor)
        result = await c.fetch_page(
            "HR", "employees", 20, 10, order_by="employee_id", order_dir="DESC"
        )
        assert result.success is True
        sql, params = cursor.execute.call_args[0]
        assert 'SELECT * FROM "HR"."EMPLOYEES" ORDER BY "employee_id" DESC' in sql
        assert "OFFSET :offset_rows ROWS FETCH NEXT :fetch_rows ROWS ONLY" in sql
        assert params == {"offset_rows": 20, "fetch_rows": 10}

    async def test_fetch_page_default_order(self, fake_oracledb) -> None:
        cursor = make_cursor(description=[("ID", "NUMBER")], rows=[])
        c = connected(fake_oracledb, cursor)
        await c.fetch_page("HR", "t", 0, 50)
        sql = cursor.execute.call_args[0][0]
        assert "ORDER BY" not in sql
