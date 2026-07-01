"""Verify all modified Python files compile without syntax errors."""
import py_compile
import sys

files = [
    r"open_navicat\services\ai_service.py",
    r"open_navicat\cli\ai_cmd.py",
    r"open_navicat\cli\conn_cmd.py",
    r"open_navicat\cli\data_cmd.py",
    r"open_navicat\ui\dialogs\connection_dialog.py",
    r"open_navicat\ui\widgets\ai_copilot.py",
    r"open_navicat\ui\widgets\schema_sync_panel.py",
    r"open_navicat\ui\widgets\data_sync_panel.py",
    r"open_navicat\dal\local_config.py",
    r"open_navicat\i18n\__init__.py",
]

errors = []
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"  ✅ {f}")
    except py_compile.PyCompileError as e:
        print(f"  ❌ {f}: {e}")
        errors.append(f)

if errors:
    print(f"\n❌ {len(errors)} file(s) have syntax errors!")
    sys.exit(1)
else:
    print(f"\n✅ All {len(files)} files compile OK")
