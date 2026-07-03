# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for OpenNavicat GUI.
Version info is generated from open_navicat/__init__.py metadata.
"""
# pylint: skip-file

import sys
from pathlib import Path
from PyInstaller.utils.hooks.qt import pyside6_library_info

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
        StringStruct(u'FileDescription', u'{open_navicat.__app_name__} - {open_navicat.__description__}'),
        StringStruct(u'FileVersion', u'{VER_STR}.0'),
        StringStruct(u'InternalName', u'opennavicat'),
        StringStruct(u'LegalCopyright', u'{open_navicat.__copyright__}'),
        StringStruct(u'OriginalFilename', u'opennavicat.exe'),
        StringStruct(u'ProductName', u'{open_navicat.__app_name__}'),
        StringStruct(u'ProductVersion', u'{VER_STR}.0')])]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])])
"""
with open("version_info.txt", "w", encoding="utf-8") as f:
    f.write(_VERSION_INFO)

block_cipher = None
src = Path(SPECPATH) / "open_navicat"

# ── Qt modules we actually use ───────────────────────────────────────────────
NEEDED = [
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "PySide6.QtPrintSupport", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtNetwork", "PySide6.QtXml", "PySide6.QtConcurrent",
    "PySide6.QtDBus",
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

all_hidden.update([
    "open_navicat.ui.themes.pro_dark",
    "open_navicat.ui.themes.pro_light",
    "shiboken6", "inspect",
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
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="opennavicat",
    version="version_info.txt",
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True,
    upx_exclude=["Qt6*.dll", "shiboken6*.dll"],
    runtime_tmpdir=None, console=False,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=str(src / "ui" / "resources" / "icon.ico") if (src / "ui" / "resources" / "icon.ico").exists() else None,
)
