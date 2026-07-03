"""BLOB viewer dialog — display bytes as image, text, or hex dump."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
)

from open_navicat.i18n import t


def _detect_blob_type(data: bytes) -> str:
    """Detect BLOB type: image, text, or binary."""
    if len(data) < 4:
        return "text"
    # Image magic bytes
    if data[:2] == b"\xff\xd8":
        return "image"
    if data[:4] == b"\x89PNG":
        return "image"
    if data[:2] == b"BM":
        return "image"
    if data[:4] in (b"GIF8",):
        return "image"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image"
    # Check if printable text
    try:
        data.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return "binary"


class BlobViewerDialog(QDialog):
    """Modal dialog for viewing BLOB data (image/text/hex)."""

    def __init__(self, data: bytes, column_name: str = "", parent=None) -> None:
        super().__init__(parent)
        self._data = data
        self.setWindowTitle(t("blob_viewer.title", column=column_name))
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        blob_type = _detect_blob_type(data)
        size_lbl = QLabel(t("blob_viewer.size_info", size=f"{len(data):,}", type=blob_type), self)
        layout.addWidget(size_lbl)

        tabs = QTabWidget(self)

        if blob_type == "image":
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                img_lbl = QLabel(self)
                img_lbl.setPixmap(pixmap.scaled(
                    680, 400, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tabs.addTab(img_lbl, t("blob_viewer.tab_image"))
            else:
                tabs.addTab(QLabel(t("blob_viewer.decode_failed"), self), t("blob_viewer.tab_image"))

        if blob_type == "text":
            text_edit = QPlainTextEdit(self)
            try:
                text_edit.setPlainText(data.decode("utf-8"))
            except UnicodeDecodeError:
                text_edit.setPlainText(data.decode("latin-1", errors="replace"))
            text_edit.setReadOnly(True)
            text_edit.setFont(QFont("Consolas", 10))
            tabs.addTab(text_edit, t("blob_viewer.tab_text"))

        # Hex dump tab (always shown)
        hex_edit = QPlainTextEdit(self)
        hex_edit.setPlainText(_hex_dump(data))
        hex_edit.setReadOnly(True)
        hex_edit.setFont(QFont("Consolas", 10))
        tabs.addTab(hex_edit, t("blob_viewer.tab_hex"))

        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def sizeHint(self):
        return self.size()


def _hex_dump(data: bytes, bytes_per_line: int = 16) -> str:
    """Format bytes as traditional hex dump."""
    lines = []
    for i in range(0, len(data), bytes_per_line):
        chunk = data[i:i + bytes_per_line]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        # Pad hex for alignment
        hex_padded = hex_part.ljust(bytes_per_line * 3 - 1)
        lines.append(f"{i:08x}  {hex_padded}  |{ascii_part}|")
    return "\n".join(lines)
