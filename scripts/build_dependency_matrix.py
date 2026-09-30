"""Generate docs/module_dependency_matrix.md from the real import graph.

Run:  python scripts/build_dependency_matrix.py

The script walks ``open_navicat``, resolves every intra-package import with
``ast`` (no execution, so optional drivers stay out of the way), buckets each
module into the agreed layering and reports:

* a layer x layer edge matrix, and
* **violations** — edges where a foundational module depends on something
  above it, which is what actually rots a layered codebase.

The layer table below is the single source of truth for the architecture
review; when you add a package, add it here.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "open_navicat"
OUT = ROOT / "docs" / "module_dependency_matrix.md"

# higher number == higher level; depending on a higher layer is a violation
LAYERS: dict[str, int] = {
    "models": 0,
    "errors": 0,
    "drivers": 1,
    "dal": 1,
    "utils": 1,
    "config": 1,
    "services": 2,
    "plugin": 2,
    "plugins": 2,
    "i18n": 1,
    "app": 3,
    "main": 3,
    "cli_main": 3,
    "gui_main": 3,
}

LAYER_TITLES = {
    0: "L0 · 无内部依赖（models / errors）",
    1: "L1 · 基础设施（drivers / dal / utils / config）",
    2: "L2 · 业务服务（services / plugin）",
    3: "L3 · 入口层（cli / ui）",
}


def unit_id(path: pathlib.Path) -> str | None:
    """``open_navicat/dal/foo.py`` -> ``open_navicat.dal.foo`` (None for packages)."""
    rel = path.relative_to(ROOT)
    if rel.suffix != ".py":
        return None
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def top_unit(module: str) -> str:
    """Collapse ``open_navicat.drivers.mysql_connector`` -> ``open_navicat.drivers``."""
    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else parts[0]


def _deferred_ids(tree: ast.Module) -> set[int]:
    """ids of nodes that are NOT eagerly imported.

    Layering is about eager (top-level) coupling.  Two common benign patterns
    must be excluded:

    * an import inside a function body — the standard lazy extension point,
    * an import guarded by ``if TYPE_CHECKING:`` — never imported at runtime.
    """
    deferred: set[int] = set()
    for func in ast.walk(tree):
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(func):
                deferred.add(id(sub))
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if getattr(test, "id", "") == "TYPE_CHECKING":
                for sub in ast.walk(node):
                    deferred.add(id(sub))
    return deferred


def _import_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module]
    return []


def scan() -> list[tuple[str, str, pathlib.Path]]:
    """Return ``(from_unit, to_unit, file)`` for every *eager* intra-package import."""
    edges: list[tuple[str, str, pathlib.Path]] = []
    for path in sorted(PKG.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        src_unit = unit_id(path)
        if src_unit is None:
            continue
        deferred = _deferred_ids(tree)
        for node in ast.walk(tree):
            if id(node) in deferred:
                continue
            for name in _import_names(node):
                if name == "open_navicat" or name.startswith("open_navicat."):
                    tgt = top_unit(name)
                    if src_unit != tgt:
                        edges.append((src_unit, tgt, path))
    return edges


def layer_of(unit: str) -> int | None:
    key = unit.split(".")[1] if unit.startswith("open_navicat.") else unit
    return LAYERS.get(key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; fail if the committed matrix is stale or a layering "
        "violation exists (architecture guard for CI)",
    )
    args = parser.parse_args(argv)

    edges = scan()
    matrix = defaultdict(int)
    violations: list[tuple[str, str, int, int, pathlib.Path]] = []
    for src, tgt, path in edges:
        matrix[(top_unit(src), top_unit(tgt))] += 1
        ls, lt = layer_of(src), layer_of(tgt)
        if ls is not None and lt is not None and lt > ls:
            violations.append((src, tgt, ls, lt, path))

    tops = sorted({u for pair in matrix for u in pair})
    lines: list[str] = []
    lines.append("# 模块依赖矩阵")
    lines.append("")
    lines.append("> 由 `scripts/build_dependency_matrix.py` 自动生成——不要手改这份表格。")
    lines.append(">")
    lines.append("> 运行：`python scripts/build_dependency_matrix.py`")
    lines.append("")
    lines.append("## 分层约定")
    lines.append("")
    lines.append("| 层 | 包 | 规则 |")
    lines.append("| --- | --- | --- |")
    for lv in sorted(LAYER_TITLES):
        pkgs = [k for k, v in LAYERS.items() if v == lv]
        lines.append(
            f"| {lv} | `{'/`, `'.join(pkgs)}` | {LAYER_TITLES[lv].split('·')[-1].strip()} |"
        )
    lines.append("")
    lines.append("允许方向：**只能依赖同层或更低层**。从低层指向高层的边就是违规。")
    lines.append("")
    lines.append("## 依赖矩阵（边数）")
    lines.append("")
    header = "| 依赖方 \\ 被依赖方 | " + " | ".join(t.split(".")[-1] for t in tops) + " |"
    lines.append(header)
    lines.append("| --- " * (len(tops) + 1) + "|")
    for a in tops:
        row = [a.split(".")[-1]]
        for b in tops:
            n = matrix.get((a, b), 0)
            row.append(str(n) if n else "·")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append(f"统计：扫描到 **{len(edges)}** 条包内导入边，覆盖 **{len(tops)}** 个顶层模块。")
    lines.append("")
    lines.append("## 违规清单")
    lines.append("")
    if not violations:
        lines.append("**无违规**——所有导入都指向同层或更低层。")
    else:
        lines.append(f"发现 **{len(violations)}** 条从低层指向高层的依赖：")
        lines.append("")
        lines.append("| 模块 | 依赖了 | 层 | → | 文件 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for src, tgt, ls, lt, path in violations:
            lines.append(f"| `{src}` | `{tgt}` | {ls} | {lt} | `{path.relative_to(ROOT)}` |")
    lines.append("")
    rendered = "\n".join(lines) + "\n"
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        stale = current != rendered
        if stale or violations:
            if stale:
                print(
                    f"{OUT.relative_to(ROOT)} is stale — rerun "
                    "`python scripts/build_dependency_matrix.py`",
                    file=sys.stderr,
                )
            print(
                f"dependency check FAILED — {len(edges)} edges, {len(violations)} violation(s)",
                file=sys.stderr,
            )
            return 1
        print(f"dependency check OK — {len(edges)} edges, 0 violation(s)")
        return 0
    OUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(edges)} edges, {len(violations)} violation(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
