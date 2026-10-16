"""In-memory stand-ins for the services the MCP tools call.

Shared by ``test_mcp_tools`` (tools as plain functions) and ``test_mcp_server``
(the same tools behind the protocol), so the two cannot drift apart.
"""

from __future__ import annotations

import importlib
from typing import Any, Iterator

import pytest

from open_navicat.models import ColumnMeta, DatabaseInfo, QueryResult, TableInfo


class FakeConnector:
    def __init__(self, engine: str, database: str) -> None:
        self.engine = engine
        self.info = type("Info", (), {"engine": engine, "database": database})()


class FakeManager:
    def __init__(self, sessions: dict[str, FakeConnector] | None = None) -> None:
        self.sessions = sessions or {}
        self.saved: list[Any] = []
        self.connect_calls: list[tuple[str, bool]] = []
        self.last_error: Exception | None = None
        self.open_ok = True

    @property
    def active_ids(self) -> list[str]:
        return list(self.sessions)

    def get_connector(self, cid: str) -> FakeConnector | None:
        return self.sessions.get(cid)

    def get_saved(self, cid: str) -> Any:
        return next((c for c in self.saved if c.id == cid), None)

    def list_saved(self) -> list[Any]:
        return list(self.saved)

    def connect(self, info: Any, *, persist: bool = True) -> bool:
        self.connect_calls.append((info.id, persist))
        if self.open_ok:
            self.sessions[info.id] = FakeConnector(info.engine, info.database)
        return self.open_ok

    def disconnect(self, cid: str) -> None:
        self.sessions.pop(cid, None)


class FakeMetadata:
    def __init__(self) -> None:
        self.databases = [DatabaseInfo(name="app", charset="utf8mb4", table_count=3)]
        self.tables = ["users", "orders"]
        self.views = ["active_users"]
        self.routines = [("refresh", "PROCEDURE")]
        self.table_info: TableInfo | None = None
        self.create_sql = "CREATE TABLE users (id INT)"

    def list_databases(self, cid: str) -> list[DatabaseInfo]:
        return self.databases

    def list_tables(self, cid: str, db: str) -> list[str]:
        return self.tables

    def list_views(self, cid: str, db: str) -> list[str]:
        return self.views

    def list_routines(self, cid: str, db: str) -> list[tuple[str, str]]:
        return self.routines

    def get_table_info(self, cid: str, db: str, table: str) -> TableInfo | None:
        return self.table_info

    def get_create_table_sql(self, cid: str, db: str, table: str) -> str:
        return self.create_sql


class FakeQueryEngine:
    def __init__(self, result: QueryResult | None = None) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.result = result or QueryResult(
            success=True,
            columns=[
                ColumnMeta(name="id", data_type="int"),
                ColumnMeta(name="total", data_type="decimal"),
            ],
            rows=[[1, "10.50"]],
            row_count=1,
            execution_time_ms=1.5,
        )

    def execute(self, cid: str, sql: str, timeout: Any = None, **kwargs: Any) -> QueryResult:
        self.calls.append((cid, sql, timeout))
        return self.result


def saved_connection(cid: str = "c1", **overrides: Any) -> Any:
    from open_navicat.models.connection import ConnectionInfo

    fields: dict[str, Any] = {
        "engine": "mysql",
        "name": "Local",
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "hunter2",
        "database": "app",
    }
    fields.update(overrides)
    info = ConnectionInfo(**fields)
    info.id = cid
    return info


def _module(name: str) -> Any:
    # ``import a.b.c as m`` binds the singleton that ``a.b.__init__`` re-exports
    # under the same name, so the module is looked up directly instead.
    return importlib.import_module(name)


@pytest.fixture()
def manager(monkeypatch) -> FakeManager:
    cm = _module("open_navicat.services.connection_manager")
    fake = FakeManager({"c1": FakeConnector("mysql", "app")})
    fake.saved = [saved_connection()]
    monkeypatch.setattr(cm, "connection_manager", fake)
    return fake


@pytest.fixture()
def metadata(monkeypatch) -> FakeMetadata:
    ms = _module("open_navicat.services.metadata_service")
    fake = FakeMetadata()
    monkeypatch.setattr(ms, "metadata_service", fake)
    return fake


@pytest.fixture()
def engine(monkeypatch) -> FakeQueryEngine:
    qe = _module("open_navicat.services.query_engine")
    fake = FakeQueryEngine()
    monkeypatch.setattr(qe, "query_engine", fake)
    return fake


@pytest.fixture()
def inline(monkeypatch) -> Iterator[None]:
    """Keep tool work on the calling thread, as ``ServiceRunner`` would not."""

    class _InlineRunner:
        def submit(self, call, timeout=None):  # noqa: ANN001, ARG002
            return call()

    from open_navicat.mcp import tools

    monkeypatch.setattr(tools, "service_runner", _InlineRunner())
    yield


@pytest.fixture()
def wired(manager, metadata, engine, inline) -> tuple:
    return manager, metadata, engine
