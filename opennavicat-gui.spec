# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for OpenNavicat GUI — optimized for size.
Only includes Qt modules actually used by the app.
"""

from pathlib import Path
from PyInstaller.utils.hooks.qt import pyside6_library_info

block_cipher = None
src = Path(SPECPATH) / "open_navicat"

# ── Qt modules we actually need ──────────────────────────────────────────────
NEEDED = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtXml",
    "PySide6.QtConcurrent",
    "PySide6.QtDBus",   # needed on Linux for Qt internal IPC
]

all_binaries = []
all_hidden = set()

for mod in NEEDED:
    try:
        h, b, _ = pyside6_library_info.collect_module(mod)
        all_hidden.update(h)
        all_binaries.extend(b)
    except Exception:
        pass

# Theme modules (dynamically imported via importlib, invisible to scanner)
all_hidden.update([
    "open_navicat.ui.themes.pro_dark",
    "open_navicat.ui.themes.pro_light",
    "shiboken6",
    "inspect",
    "PySide6.support.deprecated",
])

a = Analysis(
    [str(src / "gui_main.py")],
    pathex=[SPECPATH],
    binaries=all_binaries,
    datas=[
        (str(src / "i18n"), "open_navicat/i18n"),
        (str(src / "ui" / "resources"), "open_navicat/ui/resources"),
    ],
    hiddenimports=list(all_hidden),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="opennavicat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["Qt6*.dll", "shiboken6*.dll"],   # Qt DLLs: don't compress (may crash)
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(src / "ui" / "resources" / "icon.ico") if (src / "ui" / "resources" / "icon.ico").exists() else None,
)
