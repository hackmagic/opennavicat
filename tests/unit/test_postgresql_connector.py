from __future__ import annotations

from open_navicat.dal.postgresql_connector import _parse_cmd_tag
from open_navicat.models.connection import ConnectionInfo


class TestParseCmdTag:
    def test_insert(self) -> None:
        assert _parse_cmd_tag("INSERT 0 1") == 1

    def test_update(self) -> None:
        assert _parse_cmd_tag("UPDATE 3") == 3

    def test_delete(self) -> None:
        assert _parse_cmd_tag("DELETE 5") == 5

    def test_no_count(self) -> None:
        assert _parse_cmd_tag("CREATE TABLE") == 0

    def test_empty(self) -> None:
        assert _parse_cmd_tag("") == 0


class TestPostgreSQLConnectorEngine:
    def test_engine_default_mysql(self) -> None:
        info = ConnectionInfo()
        assert info.engine == "mysql"

    def test_engine_postgresql(self) -> None:
        info = ConnectionInfo(engine="postgresql", host="10.0.0.1", port=5432)
        assert info.engine == "postgresql"
        assert info.port == 5432

    def test_dsn_with_engine(self) -> None:
        info = ConnectionInfo(engine="postgresql", user="pguser", host="db.example.com", port=5432)
        assert info.dsn.startswith("postgresql://")
        assert "pguser" in info.dsn
        assert "db.example.com" in info.dsn

    def test_dsn_mysql_default(self) -> None:
        info = ConnectionInfo(host="localhost", user="root")
        assert info.dsn.startswith("mysql://")
