# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for OpenNavicat CLI (no Qt)."""

from pathlib import Path

block_cipher = None
src = Path(SPECPATH) / "open_navicat"

a = Analysis(
    [str(src / "cli_main.py")],
    pathex=[SPECPATH],
    binaries=[],
    datas=[
        (str(src / "i18n"), "open_navicat/i18n"),
    ],
    hiddenimports=[
        "open_navicat",
        "open_navicat.cli",
        "open_navicat.cli.app",
        "open_navicat.dal",
        "open_navicat.dal.base_connector",
        "open_navicat.dal.connection_pool",
        "open_navicat.dal.local_config",
        "open_navicat.dal.mysql_connector",
        "open_navicat.dal.postgresql_connector",
        "open_navicat.dal.sqlite_connector",
        "open_navicat.dal.ssh_tunnel",
        "open_navicat.models",
        "open_navicat.services",
        "open_navicat.config",
        "open_navicat.utils",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtSvg",
        "PySide6.QtPrintSupport",
        "PySide6.QtSvgWidgets",
        "shiboken6",
        "matplotlib",
        "numpy",
        "pandas",
    ],
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
    name="opennavicat-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
