# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for OpenNavicat GUI (with PySide6/Qt).
Qt DLLs/plugins are collected automatically by PyInstaller's PySide6 hooks.
Entry point (gui_main.py) must import PySide6 modules at top level.
"""

from pathlib import Path

block_cipher = None
src = Path(SPECPATH) / "open_navicat"

a = Analysis(
    [str(src / "gui_main.py")],
    pathex=[SPECPATH],
    binaries=[],
    datas=[
        (str(src / "i18n"), "open_navicat/i18n"),
        (str(src / "ui" / "resources"), "open_navicat/ui/resources"),
    ],
    hiddenimports=[
        "shiboken6",
        "PySide6.support.deprecated",
    ],
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
