"""Connection dialog tests.

Qt-dependent behaviour is skipped when PySide6 is absent (conftest mocks it in
that case, so widgets cannot be instantiated).
"""

from __future__ import annotations

import pytest

from open_navicat.drivers.registry import DRIVER_REGISTRY
from open_navicat.models.connection import ConnectionInfo


def test_import() -> None:
    import open_navicat.ui.dialogs.connection_dialog  # noqa: F401


def _qt_available() -> bool:
    from unittest.mock import MagicMock

    import PySide6

    return not isinstance(PySide6.QtWidgets, MagicMock)


@pytest.fixture(scope="module")
def qapp():
    if not _qt_available():
        pytest.skip("PySide6 is not installed")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class TestEngineCombo:
    def test_combo_lists_every_registered_engine(self, qapp) -> None:
        from open_navicat.ui.dialogs.connection_dialog import ConnectionDialog

        dialog = ConnectionDialog()
        data = [
            dialog._combo_engine.itemData(i) for i in range(dialog._combo_engine.count())
        ]
        assert data == list(DRIVER_REGISTRY)

    def test_labels_are_translated_or_spec_names(self, qapp) -> None:
        from open_navicat.ui.dialogs.connection_dialog import ConnectionDialog

        dialog = ConnectionDialog()
        for i, (engine, spec) in enumerate(DRIVER_REGISTRY.items()):
            text = dialog._combo_engine.itemText(i)
            assert text and text != f"connection.engine_{engine}"
            # Either the i18n string or the registry display name — never a raw key.
            assert text in (spec.display_name,) or not text.startswith("connection.")

    def test_selecting_engine_applies_registry_port(self, qapp) -> None:
        from open_navicat.ui.dialogs.connection_dialog import ConnectionDialog

        dialog = ConnectionDialog()
        dialog._combo_engine.setCurrentIndex(dialog._combo_engine.findData("clickhouse"))
        assert dialog._spin_port.value() == DRIVER_REGISTRY["clickhouse"].default_port
        dialog._combo_engine.setCurrentIndex(dialog._combo_engine.findData("oracle"))
        assert dialog._spin_port.value() == DRIVER_REGISTRY["oracle"].default_port

    @pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
    def test_file_engines_disable_host_port_and_credentials(self, qapp, engine) -> None:
        from open_navicat.ui.dialogs.connection_dialog import ConnectionDialog

        dialog = ConnectionDialog()
        dialog._combo_engine.setCurrentIndex(dialog._combo_engine.findData(engine))
        assert dialog._spin_port.isEnabled() is False
        assert dialog._edit_user.isEnabled() is False
        assert dialog._edit_password.isEnabled() is False
        # The database field carries the file path, so it stays editable.
        assert dialog._edit_database.isEnabled() is True

    def test_roundtrip_keeps_new_engine(self, qapp) -> None:
        from open_navicat.ui.dialogs.connection_dialog import ConnectionDialog

        info = ConnectionInfo(name="ch", engine="clickhouse", host="ch01", port=8123, user="default")
        dialog = ConnectionDialog(info=info)
        assert dialog._combo_engine.currentData() == "clickhouse"
        assert dialog.connection_info().engine == "clickhouse"
        assert dialog._spin_port.value() == 8123

