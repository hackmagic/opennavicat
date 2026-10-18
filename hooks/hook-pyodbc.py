# -*- mode: python ; coding: utf-8 -*-
"""Local PyInstaller hook that overrides the bundled pyodbc hook.

PyInstaller ships ``hook-pyodbc.py`` which calls
``get_pyextension_imports('pyodbc')`` — a helper that *imports* the extension
module in-process to discover its hidden imports.  That import fails on build
machines where unixODBC is not installed (notably the macOS GitHub runner,
where pyodbc's wheel links against ``libodbc.2.dylib``), which aborts the whole
analysis with a traceback inside ``PyInstaller/depend/analysis.py``.

pyodbc is a single binary extension with no Python-level submodules, so the
extra imports that helper discovers are not needed: modulegraph collects the
extension itself as a binary without executing it.  Declaring an empty list
keeps pyodbc in the frozen binary while making the analysis independent of the
build host's ODBC installation.

Users still need an ODBC driver manager at *runtime* to talk to SQL Server —
see docs/DEPLOYMENT.md.
"""

hiddenimports = []
