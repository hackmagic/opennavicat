"""Import/Export Wizard — multi-step dialogs for data import and export."""

from __future__ import annotations

import csv
import itertools

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from open_navicat.dal.connection_pool import _get_loop, connection_pool
from open_navicat.i18n import t


class FormatPage(QWizardPage):
    """Page 1: select import/export format."""

    #: Only formats the streaming pipeline (formats.importers / exporters)
    #: actually handles.  The legacy in-memory readers (txt/xml/html/dbf/mdb)
    #: were removed together with their buggy whole-file parsing: picking an
    #: unsupported format in the wizard now cannot silently mis-import data.
    FORMATS_IMPORT = [
        ("csv", t("import_export.file_type.csv")),
        ("tsv", t("import_export.file_type.tsv")),
        ("json", t("import_export.file_type.json")),
        ("jsonl", t("import_export.file_type.jsonl")),
        ("xlsx", t("import_export.file_type.excel")),
    ]

    FORMATS_EXPORT = [
        ("csv", t("import_export.file_type.csv")),
        ("tsv", t("import_export.file_type.tsv")),
        ("json", t("import_export.file_type.json")),
        ("markdown", t("import_export.file_type.markdown")),
        ("xlsx", t("import_export.file_type.excel")),
        ("sql", t("import_export.file_type.sql")),
    ]

    def __init__(self, is_import: bool = True) -> None:
        super().__init__()
        self._is_import = is_import
        self.setTitle(t("import_export.step_format"))
        self._group = QButtonGroup(self)
        layout = QVBoxLayout(self)
        self.FORMATS = self.FORMATS_IMPORT if is_import else self.FORMATS_EXPORT
        for i, (_, label) in enumerate(self.FORMATS):
            rb = QRadioButton(label)
            layout.addWidget(rb)
            self._group.addButton(rb, i)
        self._group.buttons()[1].setChecked(True)  # Default: CSV

    def selected_format(self) -> str:
        return self.FORMATS[self._group.checkedId()][0]


class FilePage(QWizardPage):
    """Page 2: select source/target file path."""

    def __init__(self, is_import: bool) -> None:
        super().__init__()
        self._is_import = is_import
        self.setTitle(t("import_export.step_file"))
        layout = QFormLayout(self)
        self._path_input = QLineEdit(self)
        self._path_input.setPlaceholderText(t("import_export.file_placeholder"))
        browse_btn = QPushButton(t("import_export.btn.browse"), self)
        browse_btn.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self._path_input)
        row.addWidget(browse_btn)
        layout.addRow(t("import_export.label.file"), row)
        self.registerField("file_path*", self._path_input)

    def _browse(self) -> None:
        if self._is_import:
            filter_str = "数据文件 (*.csv *.tsv *.json *.jsonl *.xlsx);;所有文件 (*)"
        else:
            filter_str = "数据文件 (*.csv *.tsv *.json *.md *.xlsx *.sql);;所有文件 (*)"
        if self._is_import:
            path, _ = QFileDialog.getOpenFileName(
                self, t("import_export.import_file_dialog"), "", filter_str
            )
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, t("import_export.export_file_dialog"), "export", filter_str
            )
        if path:
            self._path_input.setText(path)

    def file_path(self) -> str:
        return self._path_input.text()


class OptionsPage(QWizardPage):
    """Page 3: encoding, delimiter, header row, etc."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle(t("import_export.step_options"))
        layout = QFormLayout(self)

        self._encoding_combo = QComboBox(self)
        self._encoding_combo.addItems(["utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"])
        self._encoding_combo.setCurrentText("utf-8-sig" if "import" in __name__ else "utf-8")
        layout.addRow(t("import_export.encoding") + ":", self._encoding_combo)

        self._delimiter_combo = QComboBox(self)
        self._delimiter_combo.addItems(
            [
                t("import_export.delimiter.comma"),
                t("import_export.delimiter.semicolon"),
                t("import_export.delimiter.tab"),
                t("import_export.delimiter.pipe"),
            ]
        )
        layout.addRow(t("import_export.delimiter") + ":", self._delimiter_combo)

        self._header_check = QCheckBox(t("import_export.has_header"), self)
        self._header_check.setChecked(True)
        layout.addRow(self._header_check)

        self._batch_spin = QSpinBox(self)
        self._batch_spin.setRange(10, 10000)
        self._batch_spin.setValue(500)
        self._batch_spin.setSuffix(f" {t('import_export.rows_per_batch')}")
        layout.addRow(t("import_export.label.batch_size"), self._batch_spin)

    def encoding(self) -> str:
        return self._encoding_combo.currentText()

    def delimiter(self) -> str:
        raw = self._delimiter_combo.currentText()
        return raw[0]

    def has_header(self) -> bool:
        return self._header_check.isChecked()

    def batch_size(self) -> int:
        return self._batch_spin.value()


class ConfirmPage(QWizardPage):
    """Final page: summary and execute."""

    def __init__(self, is_import: bool) -> None:
        super().__init__()
        self._is_import = is_import
        self.setTitle(t("import_export.step_confirm"))
        layout = QVBoxLayout(self)
        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._result = QLabel(self)
        self._result.setWordWrap(True)
        layout.addWidget(self._result)
        layout.addStretch()

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)

    def set_result(self, text: str) -> None:
        self._result.setText(text)


class ImportWizard(QWizard):
    """Multi-step import wizard — CSV/Excel → Database."""

    def __init__(self, connection_id: str, database: str, table: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._table = table
        self.setWindowTitle(t("import_export.wizard_title_import"))
        self.setMinimumSize(500, 400)
        self._format_page = FormatPage(is_import=True)
        self._file_page = FilePage(is_import=True)
        self._options_page = OptionsPage()
        self._confirm_page = ConfirmPage(is_import=True)
        self.addPage(self._format_page)
        self.addPage(self._file_page)
        self.addPage(self._options_page)
        self.addPage(self._confirm_page)

    def accept(self) -> None:
        self._run_import()
        super().accept()

    def _run_import(self) -> None:
        """Streamed, type-coerced, transactional import (sql/migration.py).

        The old implementation slurped the whole file into a ``list[dict]``
        and sent every value as ``str`` — no type coercion, no transaction,
        no per-row error reporting.  The migration layer does all three, so
        the wizard just forwards its options.
        """
        from open_navicat.formats.importers import ImportFileError
        from open_navicat.sql.migration import MigrationOptions, run_migration

        path = self._file_page.file_path()
        has_header = self._options_page.has_header()
        batch_size = self._options_page.batch_size()
        delim = self._options_page.delimiter() or None
        enc = self._options_page.encoding() or None

        connector = connection_pool.get(self._connection_id)
        if not connector:
            self._confirm_page.set_result(t("import_export.msg.not_connected"))
            return

        options = MigrationOptions(
            batch_size=batch_size,
            transactional=True,
            has_header=has_header,
            delimiter=delim,
            encoding=enc or "utf-8-sig",
        )
        try:
            result = _get_loop().run_until_complete(
                run_migration(connector, self._database, self._table, path, options=options)
            )
        except ImportFileError as e:
            self._confirm_page.set_result(f"{t('import_export.msg.import_failed')}: {e}")
            return
        except Exception as e:  # noqa: BLE001 - the wizard reports any failure
            self._confirm_page.set_result(f"{t('import_export.msg.import_failed')}: {e}")
            return

        if result.aborted:
            reason = result.notes or "aborted"
            self._confirm_page.set_result(f"{t('import_export.msg.import_failed')}: {reason}")
            return
        if result.rows_failed:
            head = result.errors[0] if result.errors else None
            detail = f"row {head.row_number}: {head.error}" if head else ""
            self._confirm_page.set_result(
                t(
                    "import_export.import_partial",
                    written=result.rows_written,
                    failed=result.rows_failed,
                    detail=detail,
                )
            )
            return
        self._confirm_page.set_result(
            t("import_export.import_success", count=result.rows_written)
        )


class ExportWizard(QWizard):
    """Multi-step export wizard — Database → CSV/Excel/JSON."""

    def __init__(self, connection_id: str, database: str, table: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._table = table
        self.setWindowTitle(t("import_export.wizard_title_export"))
        self.setMinimumSize(500, 400)
        self._format_page = FormatPage(is_import=False)
        self._file_page = FilePage(is_import=False)
        self._options_page = OptionsPage()
        self._confirm_page = ConfirmPage(is_import=False)
        self.addPage(self._format_page)
        self.addPage(self._file_page)
        self.addPage(self._options_page)
        self.addPage(self._confirm_page)

    def accept(self) -> None:
        self._run_export()
        super().accept()

    def _run_export(self) -> None:
        """Streamed export through formats.exporters (paged SELECT).

        The old implementation ran one ``SELECT *`` and built the whole
        result in memory, with MySQL backtick quoting hardcoded.  Now each
        page is one ``query_engine`` round-trip and identifiers are quoted
        per engine.
        """
        from open_navicat.formats.exporters import ExportFormat, export_rows
        from open_navicat.sql.quoting import limit_clause, quote_qualified

        path = self._file_page.file_path()
        fmt = self._format_page.selected_format()
        has_header = self._options_page.has_header()
        batch_size = max(1, self._options_page.batch_size())

        connector = connection_pool.get(self._connection_id)
        if not connector:
            self._confirm_page.set_result(t("import_export.msg.not_connected"))
            return

        try:
            kind = ExportFormat(fmt)
        except ValueError:
            self._confirm_page.set_result(
                f"{t('import_export.msg.export_failed')}: unknown format {fmt!r}"
            )
            return

        info = getattr(connector, "_info", None)
        engine = getattr(info, "engine", "mysql") if info else "mysql"
        ref = quote_qualified(self._table, engine, self._database)
        header: list[str] = []

        def _pages():
            """Yield one page at a time; peak memory is a single batch."""
            offset = 0
            while True:
                result = _get_loop().run_until_complete(
                    connector.execute(
                        f"SELECT * FROM {ref} " + limit_clause(batch_size, offset, engine)
                    )
                )
                if not getattr(result, "columns", None):
                    return
                rows = [list(row) for row in result.rows]
                if not rows:
                    return
                if not offset:
                    header[:] = [c.name for c in result.columns]
                yield rows
                offset += len(rows)

        try:
            pages = _pages()
            first = next(pages, None)
            if first is None:
                self._confirm_page.set_result(t("import_export.msg.no_data"))
                return
            out_header = list(header) if has_header else []
            written = export_rows(
                path, out_header, itertools.chain([first], pages), kind, table=self._table
            )
            if not written:
                self._confirm_page.set_result(t("import_export.msg.no_data"))
                return
            self._confirm_page.set_result(
                t("import_export.export_success", count=written, path=path)
            )
        except Exception as e:  # noqa: BLE001 - the wizard reports any failure
            self._confirm_page.set_result(f"{t('import_export.msg.export_failed')}: {e}")
