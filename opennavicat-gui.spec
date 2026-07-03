# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for OpenNavicat GUI (with PySide6/Qt)."""

from pathlib import Path

block_cipher = None
src = Path(SPECPATH) / "open_navicat"

# Collect PySide6 Python modules
from PyInstaller.utils.hooks import collect_all
pyside6_datas, _, pyside6_hiddenimports = collect_all("PySide6")

# Collect Qt binaries (DLLs + plugins) via PyInstaller's Qt library info
from PyInstaller.utils.hooks.qt import pyside6_library_info

all_binaries = []
all_hidden = set(pyside6_hiddenimports)

for mod in ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
            "PySide6.QtSvg", "PySide6.QtPrintSupport", "PySide6.QtSvgWidgets",
            "PySide6.QtNetwork", "PySide6.QtSql"]:
    try:
        h, b, _ = pyside6_library_info.collect_module(mod)
        all_hidden.update(h)
        all_binaries.extend(b)
    except Exception:
        pass  # Module not available, skip

a = Analysis(
    [str(src / "gui_main.py")],
    pathex=[SPECPATH],
    binaries=all_binaries,
    datas=[
        (str(src / "i18n"), "open_navicat/i18n"),
        (str(src / "ui" / "resources"), "open_navicat/ui/resources"),
    ] + pyside6_datas,
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
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(src / "ui" / "resources" / "icon.ico") if (src / "ui" / "resources" / "icon.ico").exists() else None,
)
