"""Tests for the sidebar "导入/导出" dropdown and its import/export handlers.

The reference UI this feature mirrors puts migration behind one dropdown in the
sidebar header: an entry per importable tool plus "export connections".  These
tests pin that the menu exists, that each entry dispatches the format it claims
(a classic closure bug would make every entry import as the last one), and that
the results are reported without a modal dialog blocking the suite.
"""

from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

if not isinstance(QApplication, type):  # pragma: no cover - mocked environment
    pytest.skip("PySide6 is mocked in this environment", allow_module_level=True)

from open_navicat.models.connection import ConnectionInfo  # noqa: E402
from open_navicat.services.connection_import import IMPORT_FORMATS  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class _Boxes:
    """Non-blocking QMessageBox stand-in; records what would have been shown."""

    class StandardButton:
        Yes = 1
        No = 0

    def __init__(self) -> None:
        self.information_calls: list[tuple] = []
        self.critical_calls: list[tuple] = []
        self.warning_calls: list[tuple] = []

    def information(self, *args, **kwargs):
        self.information_calls.append(args)

    def critical(self, *args, **kwargs):
        self.critical_calls.append(args)

    def warning(self, *args, **kwargs):
        self.warning_calls.append(args)

    def question(self, *args, **kwargs):
        return self.StandardButton.Yes


class _Store:
    """In-memory stand-in for the profile store."""

    def __init__(self, existing: list[ConnectionInfo] | None = None) -> None:
        self.saved: list[ConnectionInfo] = list(existing or [])

    def list_connections(self, group: str = "") -> list[ConnectionInfo]:
        return list(self.saved)

    def save_connection(self, info: ConnectionInfo) -> None:
        self.saved.append(info)

    def list_favorites(self):
        return []

    def list_groups(self):
        return sorted({c.group for c in self.saved if c.group})


class _FakeFileDialog:
    """Stand-in for QFileDialog so no test opens a real file chooser."""

    next_open: tuple[str, str] = ("", "")
    next_save: tuple[str, str] = ("", "")

    @classmethod
    def getOpenFileName(cls, *args, **kwargs):
        return cls.next_open

    @classmethod
    def getSaveFileName(cls, *args, **kwargs):
        return cls.next_save


def _module():
    return importlib.import_module("open_navicat.ui.widgets.object_browser")


@pytest.fixture
def browser(monkeypatch, qt_app):
    """A real ObjectBrowser over an in-memory store, dialogs stubbed out."""
    module = _module()
    store = _Store()
    boxes = _Boxes()
    monkeypatch.setattr(module, "local_db", store)
    monkeypatch.setattr(module, "QMessageBox", boxes)
    # The handlers import QFileDialog locally; expose a patchable module symbol
    # so a test never reaches for a real file dialog.
    monkeypatch.setattr(module, "QFileDialog", _FakeFileDialog, raising=False)
    widget = module.ObjectBrowser()
    yield widget, store, boxes
    widget.deleteLater()


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


DATAGRIP_XML = """<project><component>
  <data-source source="LOCAL" name="pg" uuid="u1" group="Prod">
    <driver-ref>postgresql</driver-ref>
    <jdbc-url>jdbc:postgresql://db.internal:5432/analytics</jdbc-url>
  </data-source>
</component></project>"""


class TestIoMenuExists:
    def test_button_is_present_with_a_menu(self, browser) -> None:
        widget, _store, _boxes = browser
        assert widget._io_button is not None
        assert widget._io_button.menu() is not None

    def test_menu_offers_one_entry_per_format_plus_export(self, browser) -> None:
        widget, _store, _boxes = browser
        menu = widget._io_button.menu()
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        module = _module()
        expected = [module.t(f"browser.import_format.{f.key}") for f in IMPORT_FORMATS]
        expected.append(module.t("browser.export_connections_menu"))
        assert labels == expected

    def test_every_label_is_translated(self, browser) -> None:
        """`t()` echoes the key when untranslated — that would leak `browser.…`."""
        widget, _store, _boxes = browser
        for action in widget._io_button.menu().actions():
            if action.isSeparator():
                continue
            assert not action.text().startswith("browser.")

    def test_button_stays_inside_the_widget(self, browser) -> None:
        """A narrow sidebar must not push the button outside its own width."""
        widget, _store, _boxes = browser
        widget.resize(320, 400)
        widget._layout_header_widgets()  # as resizeEvent does once shown
        geometry = widget._io_button.geometry()
        assert geometry.right() <= widget.width()
        assert geometry.top() >= 0
        # The search box gives up width rather than overlapping the button.
        assert widget._search_bar.geometry().right() < geometry.left()


class TestImportDispatch:
    def test_menu_entry_imports_its_own_format(self, browser, tmp_path, monkeypatch) -> None:
        """Each action must carry its own key, not the loop's last value."""
        widget, _store, _boxes = browser
        seen: list[str] = []
        monkeypatch.setattr(widget, "_import_as", lambda fmt: seen.append(fmt) or 0)
        # Rebuild the menu so the stubbed handler is the one wired up.
        widget._setup_io_menu()
        actions = [a for a in widget._io_button.menu().actions() if not a.isSeparator()]
        for action in actions[:-1]:  # last one is "export connections"
            action.trigger()
        assert seen == [f.key for f in IMPORT_FORMATS]

    def test_import_saves_parsed_connections(self, browser, tmp_path) -> None:
        widget, store, boxes = browser
        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        count = widget.import_connections(path=path)
        assert count == 1
        assert len(store.saved) == 1
        assert store.saved[0].engine == "postgresql"
        assert store.saved[0].group == "Prod"
        assert boxes.information_calls

    def test_duplicates_are_skipped_not_overwritten(self, browser, tmp_path) -> None:
        widget, store, boxes = browser
        store.saved.append(
            ConnectionInfo(
                id="keep",
                name="pg",
                engine="postgresql",
                host="db.internal",
                port=5432,
                database="analytics",
            )
        )
        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        assert widget.import_connections(path=path) == 0
        assert [c.id for c in store.saved] == ["keep"]

    def test_unrecognised_file_reports_the_parser_error(self, browser, tmp_path) -> None:
        widget, store, boxes = browser
        path = _write(tmp_path, "junk.txt", "nothing familiar here")
        assert widget.import_connections(path=path) == 0
        assert boxes.critical_calls
        assert "unrecognised" in str(boxes.critical_calls[0][-1])
        assert store.saved == []

    def test_skipped_entries_are_reported(self, browser, tmp_path) -> None:
        widget, store, boxes = browser
        path = _write(
            tmp_path,
            "dataSources.xml",
            DATAGRIP_XML.replace(
                "</component></project>",
                '<data-source source="LOCAL" name="cass" uuid="u9">'
                "<driver-ref>cassandra</driver-ref>"
                "<jdbc-url>jdbc:cassandra://n1:9042/ks</jdbc-url>"
                "</data-source></component></project>",
            ),
        )
        assert widget.import_connections(path=path) == 1
        detail = boxes.information_calls[0][-1]
        assert "1" in detail  # the skipped count is surfaced

    def test_encrypted_dbx_prompts_for_a_passphrase(self, browser, tmp_path, monkeypatch) -> None:
        widget, store, _boxes = browser
        envelope = {
            "format": "dbx-encrypted",
            "version": 1,
            "salt": "AAAA",
            "iv": "AAAA",
            "data": "AAAA",
        }
        path = _write(tmp_path, "e.dbx", json.dumps(envelope))
        prompts: list[bool] = []

        def fake_prompt():
            prompts.append(True)
            return None  # user cancelled

        monkeypatch.setattr(widget, "_ask_dbx_passphrase", fake_prompt)
        assert widget.import_connections(path=path) == 0
        assert prompts == [True]
        assert store.saved == []


class TestExport:
    def test_export_writes_a_file_that_imports_back(self, browser, tmp_path, monkeypatch) -> None:
        widget, store, boxes = browser
        store.saved.append(
            ConnectionInfo(id="a", name="shop", engine="mysql", host="h", database="d")
        )
        target = str(tmp_path / "out.json")
        monkeypatch.setattr(_FakeFileDialog, "next_save", (target, ""))
        result = widget.export_connections_file()
        assert result.startswith("1:")
        assert boxes.information_calls
        assert widget.import_connections(path=target) == 0  # duplicate
        assert len(store.saved) == 1

    def test_export_without_connections_says_so(self, browser, monkeypatch) -> None:
        widget, _store, boxes = browser
        monkeypatch.setattr(_FakeFileDialog, "next_save", ("x.json", ""))
        assert widget.export_connections_file() == ""
        assert boxes.information_calls
