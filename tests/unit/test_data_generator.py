from __future__ import annotations

from open_navicat.models.table_schema import ColumnInfo, TableInfo


def _make_table_info() -> TableInfo:
    info = TableInfo(name="users", database="testdb")
    info.columns = [
        ColumnInfo(name="id", data_type="int", nullable=False, is_auto_increment=True),
        ColumnInfo(name="name", data_type="varchar(100)", nullable=False),
        ColumnInfo(name="email", data_type="varchar(255)", nullable=True),
        ColumnInfo(name="phone", data_type="varchar(20)", nullable=True),
        ColumnInfo(name="status", data_type="int", nullable=False),
        ColumnInfo(name="amount", data_type="decimal(10,2)", nullable=True),
        ColumnInfo(name="created_at", data_type="datetime", nullable=True),
    ]
    return info


def test_singleton() -> None:
    from open_navicat.services.data_generator import DataGeneratorService
    a = DataGeneratorService()
    b = DataGeneratorService()
    assert a is b


def test_generate_returns_correct_count() -> None:
    from open_navicat.services.data_generator import data_generator
    info = _make_table_info()
    rows = data_generator.generate(info, 20)
    assert len(rows) == 20


def test_generate_skips_auto_increment() -> None:
    from open_navicat.services.data_generator import data_generator
    info = _make_table_info()
    rows = data_generator.generate(info, 5)
    for row in rows:
        assert "id" not in row


def test_generate_has_expected_keys() -> None:
    from open_navicat.services.data_generator import data_generator
    info = _make_table_info()
    rows = data_generator.generate(info, 1)
    assert len(rows) == 1
    row = rows[0]
    assert "name" in row
    assert "email" in row
    assert "phone" in row
    assert "status" in row
    assert "amount" in row
    assert "created_at" in row


def test_generate_email_format() -> None:
    from open_navicat.services.data_generator import data_generator
    info = _make_table_info()
    for _ in range(20):
        rows = data_generator.generate(info, 1)
        email = rows[0]["email"]
        if email is not None:
            assert "@" in email
            assert "." in email.split("@")[1]


def test_generate_nullable_can_be_none() -> None:
    from unittest.mock import patch

    from open_navicat.services.data_generator import data_generator
    info = _make_table_info()
    # Force null path by mocking random.random to return 0.0 (< 0.1 threshold)
    with patch("open_navicat.services.data_generator.random.random", return_value=0.0):
        rows = data_generator.generate(info, 1)
        assert rows[0].get("email") is None


def test_generate_respects_type_int() -> None:
    from open_navicat.services.data_generator import data_generator
    info = TableInfo(name="t", database="db")
    info.columns = [ColumnInfo(name="val", data_type="int", nullable=False)]
    for _ in range(20):
        rows = data_generator.generate(info, 1)
        assert isinstance(rows[0]["val"], int)


def test_generate_respects_type_decimal() -> None:
    from open_navicat.services.data_generator import data_generator
    info = TableInfo(name="t", database="db")
    info.columns = [ColumnInfo(name="val", data_type="decimal(10,2)", nullable=False)]
    for _ in range(20):
        rows = data_generator.generate(info, 1)
        assert isinstance(rows[0]["val"], float)
