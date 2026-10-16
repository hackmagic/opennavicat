"""GUI import/export wizard wiring tests.

The wizard used to slurp the whole file into a ``list[dict]`` (values all
``str``, no transaction, no error summary) and to export with one
``SELECT *`` into memory.  These tests drive the real wizard against a temp
SQLite database and assert the streaming/type-coercion path is what runs.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

if not isinstance(QApplication, type):  # pragma: no cover - mocked environment
    pytest.skip("PySide6 is mocked in this environment", allow_module_level=True)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from open_navicat.dal.connection_pool import connection_pool  # noqa: E402
from open_navicat.drivers.dsn import dsn_to_connection  # noqa: E402
from open_navicat.services.connection_manager import connection_manager  # noqa: E402
from open_navicat.ui.dialogs.import_export_wizard import (  # noqa: E402
    ExportWizard,
    ImportWizard,
)


@pytest.fixture(scope="module")
def qt_app():
    """A QApplication is required before any widget can be constructed."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def wired(tmp_path):
    """A temp SQLite db + connected profile; pool closed after the test."""
    db = tmp_path / "w.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT, score NUMERIC(5,1))")
    conn.commit()
    conn.close()

    # connect() registers the profile in the pool under info.id; saving it
    # through local_db would write into the developer's real profile store.
    info = dsn_to_connection(f"sqlite:///{db.as_posix()}", name="w")
    connection_manager.connect(info)
    cid = info.id
    try:
        yield db, cid
    finally:
        connection_pool.close_all()


class TestImportWizard:
    def test_import_coerces_types_and_reports_bad_rows(self, qt_app, wired):
        db, cid = wired
        in_csv = db.parent / "in.csv"
        in_csv.write_text(
            "id,name,score\n5,guido,93.5\n6,dennis,77\n7,bad,x\n", encoding="utf-8"
        )

        wiz = ImportWizard(cid, "main", "people")
        wiz._file_page._path_input.setText(str(in_csv))
        wiz._run_import()

        text = wiz._confirm_page._result.text()
        assert "2" in text  # 两行成功
        conn = sqlite3.connect(db)
        rows = list(conn.execute("SELECT id, score, typeof(score) FROM people"))
        conn.close()
        assert (5, 93.5, "real") in rows
        assert (6, 77.0, "integer") in rows
        assert len(rows) == 2  # 坏行未写入

    def test_import_reports_missing_file(self, qt_app, wired):
        _, cid = wired
        wiz = ImportWizard(cid, "main", "people")
        wiz._file_page._path_input.setText(str(Path("does-not-exist.csv")))
        wiz._run_import()
        text = wiz._confirm_page._result.text()
        assert text  # 有结果文本，且不抛异常


class TestExportWizard:
    def test_export_streams_rows(self, qt_app, wired):
        db, cid = wired
        conn = sqlite3.connect(db)
        conn.executemany(
            "INSERT INTO people VALUES (?,?,?)",
            [(1, "ada", 91.5), (2, "linus", 88.0)],
        )
        conn.commit()
        conn.close()

        out_csv = db.parent / "out.csv"
        wiz = ExportWizard(cid, "main", "people")
        wiz._file_page._path_input.setText(str(out_csv))
        wiz._run_export()

        text = wiz._confirm_page._result.text()
        assert "2" in text
        content = out_csv.read_text(encoding="utf-8-sig")
        assert "ada" in content
        assert "linus" in content
        assert "91.5" in content
