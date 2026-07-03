# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for OpenNavicat CLI (no Qt).
Version info is generated from open_navicat/__init__.py metadata.
"""
# pylint: skip-file

from pathlib import Path

# ── Version info generated from open_navicat/__init__.py ──────────────────────
import open_navicat
VER = tuple(int(x) for x in open_navicat.__version__.split("."))
VER_STR = ".".join(str(x) for x in VER)
_VERSION_INFO = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({VER[0]}, {VER[1]}, {VER[2]}, 0),
    prodvers=({VER[0]}, {VER[1]}, {VER[2]}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct(u'CompanyName', u'{open_navicat.__org_name__}'),
        StringStruct(u'FileDescription', u'{open_navicat.__app_name__} CLI - {open_navicat.__description__}'),
        StringStruct(u'FileVersion', u'{VER_STR}.0'),
        StringStruct(u'InternalName', u'opennavicat-cli'),
        StringStruct(u'LegalCopyright', u'{open_navicat.__copyright__}'),
        StringStruct(u'OriginalFilename', u'opennavicat-cli.exe'),
        StringStruct(u'ProductName', u'{open_navicat.__app_name__} CLI'),
        StringStruct(u'ProductVersion', u'{VER_STR}.0')])]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])])
"""
with open("version_info_cli.txt", "w", encoding="utf-8") as f:
    f.write(_VERSION_INFO)

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
        "open_navicat.cli", "open_navicat.cli.app",
        "open_navicat.dal", "open_navicat.dal.base_connector",
        "open_navicat.dal.connection_pool", "open_navicat.dal.local_config",
        "open_navicat.dal.mysql_connector", "open_navicat.dal.postgresql_connector",
        "open_navicat.dal.sqlite_connector", "open_navicat.dal.ssh_tunnel",
        "open_navicat.models", "open_navicat.services",
        "open_navicat.config", "open_navicat.utils",
    ],
    excludes=[
        "PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
        "PySide6.QtSvg", "PySide6.QtPrintSupport", "PySide6.QtSvgWidgets",
        "shiboken6", "matplotlib", "numpy", "pandas",
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="opennavicat-cli",
    version="version_info_cli.txt",
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[],
    runtime_tmpdir=None, console=True,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
