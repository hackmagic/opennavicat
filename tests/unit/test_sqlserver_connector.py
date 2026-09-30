"""Tests for the SQL Server connector (pyodbc bridged to asyncio).

pyodbc is replaced with a fake so these run without a real SQL Server.
"""

from __future__ import annotations

import datetime
import decimal
import uuid
from unittest.mock import MagicMock, patch

import pytest

from open_navicat.drivers import sqlserver_connector as mod
from open_navicat.drivers.sqlserver_connector import (
    PREFERRED_DRIVERS,
    SQLServerConnector,
    _escape,
    _normalize_value,
    _split_qualified,
    pick_odbc_driver,
)
from open_navicat.errors import DriverNotFoundError
from open_navicat.models import ConnectionInfo


class FakeCursor:
    def __init__(self, description=None, rows=(), rowcount=-1, error=None) -> None:
        self.description = description
        self._rows = list(rows)
        self.rowcount = rowcount
        self._error = error
        self.closed = False
        self.executed: list[tuple] = []

    def execute(self, sql, params=None):
        if self._error:
            raise self._error
        self.executed.append((sql, params))
        return self

    def executemany(self, sql, seq):
        if self._error:
            raise self._error
        self.executed.append((sql, list(seq)))
        self.rowcount = len(list(seq))
        return self

    def fetchall(self):
        return self._rows

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def fake_pyodbc(cursor: FakeCursor, drivers=("ODBC Driver 18 for SQL Server",)) -> MagicMock:
    fake = MagicMock()
    fake.drivers.return_value = list(drivers)
    fake.connect.return_value = FakeConnection(cursor)
    fake.SQL_TYPE_NAMES = {1: "char", 4: "int"}
    return fake


def info(**overrides) -> ConnectionInfo:
    base = dict(
        engine="sqlserver", host="sql01", port=1433, user="sa", password="pw", database="master"
    )
    base.update(overrides)
    return ConnectionInfo(**base)


class TestDriverSelection:
    def test_prefers_newest_driver(self) -> None:
        assert (
            pick_odbc_driver(["ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server"])
            == PREFERRED_DRIVERS[0]
        )

    def test_falls_back_through_the_list(self) -> None:
        assert pick_odbc_driver(["SQL Server"]) == "SQL Server"
        assert (
            pick_odbc_driver(["ODBC Driver 13 for SQL Server"]) == "ODBC Driver 13 for SQL Server"
        )

    def test_ignores_unrelated_drivers(self) -> None:
        assert pick_odbc_driver(["Microsoft Access Driver (*.mdb)"]) is None

    def test_none_when_nothing_available(self) -> None:
        assert pick_odbc_driver([]) is None


class TestIdentifierHelpers:
    def test_split_qualified(self) -> None:
        assert _split_qualified("dbo.Users") == ("dbo", "Users")
        assert _split_qualified("Sales.Orders") == ("Sales", "Orders")
        assert _split_qualified("Users") == ("dbo", "Users")

    def test_escape_closes_brackets(self) -> None:
        assert _escape("we]ird") == "we]]ird"
        assert _escape(None) == ""


class TestValueNormalization:
    def test_decimal_becomes_float(self) -> None:
        assert _normalize_value(decimal.Decimal("1.5")) == 1.5

    def test_bytes_become_hex(self) -> None:
        assert _normalize_value(b"\x01\xff") == "01ff"

    def test_datetime_becomes_iso(self) -> None:
        assert _normalize_value(datetime.datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05"

    def test_date_and_time(self) -> None:
        assert _normalize_value(datetime.date(2026, 1, 2)) == "2026-01-02"
        assert _normalize_value(datetime.time(3, 4, 5)) == "03:04:05"

    def test_uuid_and_plain_values(self) -> None:
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert _normalize_value(u) == str(u)
        assert _normalize_value(None) is None
        assert _normalize_value(42) == 42
        assert _normalize_value("x") == "x"


class TestConnectionString:
    def test_includes_server_port_and_database(self) -> None:
        conn = SQLServerConnector(info(database="appdb"))
        cs = conn._connection_string("ODBC Driver 18 for SQL Server")
        assert "DRIVER={ODBC Driver 18 for SQL Server}" in cs
        assert "SERVER=sql01,1433" in cs
        assert "DATABASE=appdb" in cs
        assert "UID=sa" in cs

    def test_omits_database_when_blank(self) -> None:
        conn = SQLServerConnector(info(database=""))
        assert "DATABASE=" not in conn._connection_string("SQL Server")

    def test_encryption_follows_the_profile(self) -> None:
        assert "Encrypt=no" in SQLServerConnector(info(use_ssl=False))._connection_string("X")
        assert "Encrypt=yes" in SQLServerConnector(info(use_ssl=True))._connection_string("X")

    def test_defaults_host_and_timeout(self) -> None:
        conn = SQLServerConnector(info(host="", port=0, connect_timeout=0))
        cs = conn._connection_string("X")
        assert "SERVER=127.0.0.1" in cs
        assert "Connection Timeout=15" in cs


class TestConnect:
    async def test_raises_when_pyodbc_missing(self) -> None:
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", None):
            with pytest.raises(DriverNotFoundError) as exc:
                await conn.connect()
        assert "sqlserver" in str(exc.value)

    async def test_raises_when_no_odbc_driver_installed(self) -> None:
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(FakeCursor(), drivers=[])):
            with pytest.raises(DriverNotFoundError) as exc:
                await conn.connect()
        assert "ODBC driver" in str(exc.value)

    async def test_connect_success(self) -> None:
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(FakeCursor())):
            assert await conn.connect() is True
        assert await conn.is_connected() is True
        await conn.disconnect()
        assert await conn.is_connected() is False

    async def test_connect_failure_keeps_the_cause(self) -> None:
        boom = RuntimeError("login failed for user 'sa'")
        fake = fake_pyodbc(FakeCursor())
        fake.connect.side_effect = boom
        conn = SQLServerConnector(info(password="hunter2"))
        with patch.object(mod, "pyodbc", fake):
            assert await conn.connect() is False
        assert conn.last_error is boom
        assert await conn.is_connected() is False

    async def test_password_is_never_reported_in_errors(self) -> None:
        conn = SQLServerConnector(info(password="hunter2"))
        fake = fake_pyodbc(FakeCursor())
        fake.connect.side_effect = RuntimeError("bad password=hunter2")
        with patch.object(mod, "pyodbc", fake):
            await conn.connect()
        # The raw driver exception is kept, but anything surfaced to a user is
        # redacted by NavicatError.from_exception at the pool boundary.
        from open_navicat.errors import NavicatError

        err = NavicatError.from_exception(conn.last_error, stage="connect")
        assert "hunter2" not in err.detail


class TestExecute:
    async def test_select_maps_columns_and_rows(self) -> None:
        cursor = FakeCursor(
            description=[
                ("id", 4, None, None, None, None, False),
                ("name", 1, 50, None, None, None, True),
            ],
            rows=[(1, "alpha"), (2, "beta")],
        )
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            result = await conn.execute("SELECT id, name FROM t")
        assert result.success is True
        assert [c.name for c in result.columns] == ["id", "name"]
        assert result.rows == [[1, "alpha"], [2, "beta"]]
        assert result.row_count == 2

    async def test_dml_reports_affected_rows(self) -> None:
        cursor = FakeCursor(description=None, rowcount=3)
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            result = await conn.execute("UPDATE t SET a = 1")
        assert result.success is True
        assert result.affected_rows == 3

    async def test_no_count_reports_zero_not_minus_one(self) -> None:
        cursor = FakeCursor(description=None, rowcount=-1)
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            result = await conn.execute("SET NOCOUNT ON")
        assert result.affected_rows == 0

    async def test_parameters_are_forwarded(self) -> None:
        cursor = FakeCursor(description=None, rowcount=1)
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            await conn.execute("UPDATE t SET a = ? WHERE id = ?", (1, 2))
        assert cursor.executed[0] == ("UPDATE t SET a = ? WHERE id = ?", (1, 2))

    async def test_driver_error_becomes_a_failed_result(self) -> None:
        cursor = FakeCursor(error=RuntimeError("Invalid object name 'nope'"))
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            result = await conn.execute("SELECT * FROM nope")
        assert result.success is False
        assert "Invalid object name" in result.error_message

    async def test_execute_without_connection(self) -> None:
        conn = SQLServerConnector(info())
        result = await conn.execute("SELECT 1")
        assert result.success is False
        assert "not open" in result.error_message

    async def test_execute_many(self) -> None:
        cursor = FakeCursor(description=None, rowcount=2)
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            assert await conn.execute_many("INSERT INTO t VALUES (?)", [(1,), (2,)]) == 2

    async def test_execute_many_empty_is_zero(self) -> None:
        conn = SQLServerConnector(info())
        assert await conn.execute_many("INSERT INTO t VALUES (?)", []) == 0


class TestMetadataQueries:
    async def test_list_databases(self) -> None:
        cursor = FakeCursor(rows=[("master", "SQL_Latin1"), ("appdb", "SQL_Latin1")])
        conn = SQLServerConnector(info())
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            dbs = await conn.list_databases()
        assert [d.name for d in dbs] == ["master", "appdb"]

    async def test_list_tables_qualifies_non_dbo_schemas(self) -> None:
        cursor = FakeCursor(rows=[("dbo", "Users"), ("Sales", "Orders")])
        conn = SQLServerConnector(info(database=""))
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            tables = await conn.list_tables("")
        assert tables == ["Users", "Sales.Orders"]

    async def test_fetch_page_uses_offset_fetch(self) -> None:
        cursor = FakeCursor(description=[], rows=[])
        conn = SQLServerConnector(info(database=""))
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            await conn.fetch_page("", "dbo.Users", offset=20, limit=10)
        sql, params = cursor.executed[-1]
        assert "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in sql
        assert params == (20, 10)

    async def test_fetch_page_without_order_by_still_valid(self) -> None:
        cursor = FakeCursor(description=[], rows=[])
        conn = SQLServerConnector(info(database=""))
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            await conn.fetch_page("", "Users", offset=0, limit=5)
        sql, _ = cursor.executed[-1]
        # SQL Server rejects OFFSET without ORDER BY.
        assert "ORDER BY (SELECT NULL)" in sql

    async def test_batch_insert_builds_parameterised_sql(self) -> None:
        cursor = FakeCursor()
        conn = SQLServerConnector(info(database=""))
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
            await conn.batch_insert("", "dbo.T", rows)
        sql, params = cursor.executed[-1]
        assert sql == "INSERT INTO [dbo].[T] ([a], [b]) VALUES (?, ?)"
        assert params == [(1, 2), (3, 4)]

    async def test_update_and_delete_escape_identifiers(self) -> None:
        cursor = FakeCursor(description=None, rowcount=1)
        conn = SQLServerConnector(info(database=""))
        with patch.object(mod, "pyodbc", fake_pyodbc(cursor)):
            await conn.connect()
            await conn.update_row("", "T", {"a": 1}, {"id": 9})
            update_sql, update_params = cursor.executed[-1]
            assert update_sql == "UPDATE [dbo].[T] SET [a] = ? WHERE [id] = ?"
            assert update_params == (1, 9)

            await conn.delete_row("", "T", {"id": 9})
            delete_sql, delete_params = cursor.executed[-1]
            assert delete_sql == "DELETE FROM [dbo].[T] WHERE [id] = ?"
            assert delete_params == (9,)

    async def test_metadata_without_connection_is_empty(self) -> None:
        conn = SQLServerConnector(info())
        assert await conn.list_tables("") == []
        assert await conn._fetch_all("SELECT 1") == []

    async def test_ping_requires_connection(self) -> None:
        conn = SQLServerConnector(info())
        assert await conn.ping() is False


class TestAsyncBridge:
    async def test_work_runs_off_the_event_loop_thread(self) -> None:
        import threading

        conn = SQLServerConnector(info())
        main = threading.get_ident()
        seen = {}

        def blocking() -> str:
            seen["thread"] = threading.get_ident()
            return "done"

        assert await conn._run(blocking) == "done"
        assert seen["thread"] != main
        await conn.disconnect()

    async def test_all_work_uses_the_same_worker_thread(self) -> None:
        """ODBC connections are not safe to share across threads."""
        import threading

        conn = SQLServerConnector(info())
        threads = []

        def record() -> None:
            threads.append(threading.get_ident())

        await conn._run(record)
        await conn._run(record)
        await conn._run(record)
        assert len(set(threads)) == 1
        await conn.disconnect()

    async def test_disconnect_is_idempotent(self) -> None:
        conn = SQLServerConnector(info())
        await conn.disconnect()
        await conn.disconnect()


class TestDsnIntegration:
    def test_sqlserver_dsn_maps_to_connection_info(self) -> None:
        from open_navicat.drivers.dsn import dsn_to_connection

        got = dsn_to_connection("sqlserver://sa:pw@sql01:1433/master")
        assert got.engine == "sqlserver"
        assert (got.host, got.port, got.database) == ("sql01", 1433, "master")
        assert got.password == "pw"

    def test_mssql_alias(self) -> None:
        from open_navicat.drivers.dsn import parse_dsn

        assert parse_dsn("mssql://sa@h/master").engine == "sqlserver"
