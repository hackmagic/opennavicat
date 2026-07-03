# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for OpenNavicat GUI (with PySide6/Qt).
Uses pyside6_library_info.collect_module() for DLL collection
(based on .pyd binary scanning, not Python package introspection).
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks.qt import pyside6_library_info

block_cipher = None
src = Path(SPECPATH) / "open_navicat"

# Collect all PySide6 submodules (walks directory, works on 6.11+)
all_hidden = set(collect_submodules("PySide6"))
all_hidden.update(["shiboken6", "inspect", "PySide6.support.deprecated",
                    "open_navicat.ui.themes.pro_dark",
                    "open_navicat.ui.themes.pro_light"])

# Collect Qt DLLs/plugins via link-time .pyd scanning (avoids package-structure issues)
all_binaries = []
for mod in [
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "PySide6.QtSvg", "PySide6.QtPrintSupport", "PySide6.QtSvgWidgets",
    "PySide6.QtNetwork", "PySide6.QtSql",
    "PySide6.QtDBus", "PySide6.QtConcurrent",
]:
    try:
        h, b, _ = pyside6_library_info.collect_module(mod)
        all_hidden.update(h)
        all_binaries.extend(b)
    except Exception:
        pass

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
