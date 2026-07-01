from __future__ import annotations

from open_navicat.models.table_schema import ColumnInfo, ForeignKeyInfo, IndexInfo, TableInfo
from open_navicat.services.sync_engine import ColumnDiff, SyncEngine


class TestColumnChanged:
    def setup_method(self) -> None:
        self._engine = SyncEngine()

    def test_type_changed(self) -> None:
        a = ColumnInfo(name="c", data_type="INT")
        b = ColumnInfo(name="c", data_type="VARCHAR")
        assert self._engine._column_changed(a, b) is True

    def test_nullable_changed(self) -> None:
        a = ColumnInfo(name="c", data_type="INT", nullable=False)
        b = ColumnInfo(name="c", data_type="INT", nullable=True)
        assert self._engine._column_changed(a, b) is True

    def test_primary_key_changed(self) -> None:
        a = ColumnInfo(name="c", data_type="INT", is_primary_key=True)
        b = ColumnInfo(name="c", data_type="INT", is_primary_key=False)
        assert self._engine._column_changed(a, b) is True

    def test_auto_increment_changed(self) -> None:
        a = ColumnInfo(name="c", data_type="INT", is_auto_increment=True)
        b = ColumnInfo(name="c", data_type="INT", is_auto_increment=False)
        assert self._engine._column_changed(a, b) is True

    def test_unchanged(self) -> None:
        a = ColumnInfo(name="c", data_type="INT", nullable=False, is_primary_key=True)
        b = ColumnInfo(name="c", data_type="INT", nullable=False, is_primary_key=True)
        assert self._engine._column_changed(a, b) is False

    def test_char_length_changed(self) -> None:
        a = ColumnInfo(name="c", data_type="VARCHAR", char_max_length=255)
        b = ColumnInfo(name="c", data_type="VARCHAR", char_max_length=100)
        assert self._engine._column_changed(a, b) is True

    def test_precision_changed(self) -> None:
        a = ColumnInfo(name="c", data_type="DECIMAL", numeric_precision=10, numeric_scale=2)
        b = ColumnInfo(name="c", data_type="DECIMAL", numeric_precision=8, numeric_scale=2)
        assert self._engine._column_changed(a, b) is True


class TestCompareTable:
    def setup_method(self) -> None:
        self._engine = SyncEngine()

    def test_identical_tables(self) -> None:
        src = TableInfo(name="t", database="db",
                        columns=[ColumnInfo(name="id", data_type="INT")])
        tgt = TableInfo(name="t", database="db",
                        columns=[ColumnInfo(name="id", data_type="INT")])
        assert self._engine._compare_table(src, tgt) is None

    def test_added_column(self) -> None:
        src = TableInfo(name="t", database="db",
                        columns=[ColumnInfo(name="id", data_type="INT"),
                                 ColumnInfo(name="name", data_type="VARCHAR")])
        tgt = TableInfo(name="t", database="db",
                        columns=[ColumnInfo(name="id", data_type="INT")])
        td = self._engine._compare_table(src, tgt)
        assert td is not None
        assert len(td.added_columns) == 1
        assert td.added_columns[0].name == "name"

    def test_removed_column(self) -> None:
        src = TableInfo(name="t", database="db",
                        columns=[ColumnInfo(name="id", data_type="INT")])
        tgt = TableInfo(name="t", database="db",
                        columns=[ColumnInfo(name="id", data_type="INT"),
                                 ColumnInfo(name="old", data_type="VARCHAR")])
        td = self._engine._compare_table(src, tgt)
        assert td is not None
        assert td.removed_columns == ["old"]

    def test_modified_column_passes_source(self) -> None:
        src = TableInfo(name="t", database="db",
                        columns=[ColumnInfo(name="c", data_type="VARCHAR",
                                            char_max_length=255, nullable=False,
                                            default="hello")])
        tgt = TableInfo(name="t", database="db",
                        columns=[ColumnInfo(name="c", data_type="VARCHAR",
                                            char_max_length=100, nullable=True)])
        td = self._engine._compare_table(src, tgt)
        assert td is not None
        assert len(td.modified_columns) == 1
        cd = td.modified_columns[0]
        assert cd.source_column is not None
        assert cd.source_column.char_max_length == 255
        assert cd.source_column.nullable is False
        assert cd.source_column.default == "hello"


class TestGenerateSyncScript:
    def setup_method(self) -> None:
        self._engine = SyncEngine()

    def test_added_index_primary_key(self) -> None:
        from open_navicat.services.sync_engine import SyncDiff, TableDiff
        diff = SyncDiff()
        td = TableDiff(table_name="t")
        td.added_indexes.append(IndexInfo(name="PRIMARY", columns=["id"],
                                          is_primary=True, is_unique=True))
        diff.modified_tables.append(td)
        stmts = self._engine.generate_sync_script(diff)
        assert any("ADD PRIMARY KEY" in s for s in stmts)
        assert not any("UNIQUE INDEX" in s for s in stmts)

    def test_added_index_unique(self) -> None:
        from open_navicat.services.sync_engine import SyncDiff, TableDiff
        diff = SyncDiff()
        td = TableDiff(table_name="t")
        td.added_indexes.append(IndexInfo(name="idx_email", columns=["email"],
                                          is_unique=True, is_primary=False))
        diff.modified_tables.append(td)
        stmts = self._engine.generate_sync_script(diff)
        assert any("UNIQUE INDEX" in s for s in stmts)

    def test_modified_column_uses_full_info(self) -> None:
        from open_navicat.services.sync_engine import SyncDiff, TableDiff
        diff = SyncDiff()
        td = TableDiff(table_name="t")
        td.modified_columns.append(ColumnDiff(
            column_name="c",
            source_column=ColumnInfo(name="c", data_type="VARCHAR",
                                     char_max_length=255, nullable=False),
        ))
        diff.modified_tables.append(td)
        stmts = self._engine.generate_sync_script(diff)
        matching = [s for s in stmts if "MODIFY COLUMN" in s]
        assert len(matching) == 1
        assert "255" in matching[0]
        assert "NOT NULL" in matching[0]
