"""Object catalog: a searchable index of everything a connection holds.

The object tree used to render each category as it was expanded and keep the
results in widget items, so there was no way to answer "where is the table called
orders?" across a database, let alone across connections.  This module builds an
in-memory index from driver listings and answers searches over it, with no Qt
dependency so the behaviour can be tested directly.

Kinds that a driver cannot report (many engines have no standalone indexes, and
DuckDB has no triggers) simply do not appear rather than showing an empty branch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence


class ObjectKind(str, Enum):
    """A kind of schema object the browser can show."""

    TABLE = "table"
    VIEW = "view"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    TRIGGER = "trigger"
    INDEX = "index"
    CONSTRAINT = "constraint"
    COLUMN = "column"
    QUERY = "query"


#: Display order for the tree: data first, then code, then supporting objects.
KIND_ORDER: tuple[ObjectKind, ...] = (
    ObjectKind.TABLE,
    ObjectKind.VIEW,
    ObjectKind.PROCEDURE,
    ObjectKind.FUNCTION,
    ObjectKind.TRIGGER,
    ObjectKind.INDEX,
    ObjectKind.CONSTRAINT,
    ObjectKind.COLUMN,
    ObjectKind.QUERY,
)


@dataclass(frozen=True)
class ObjectRef:
    """One catalogued object."""

    kind: ObjectKind
    name: str
    connection_id: str = ""
    connection_name: str = ""
    database: str = ""
    parent: str = ""
    detail: str = ""

    @property
    def qualified_name(self) -> str:
        """``db.table`` when a database is known, else just the name."""
        return f"{self.database}.{self.name}" if self.database else self.name

    @property
    def display(self) -> str:
        """Label for a tree row or a search result."""
        if self.parent:
            return f"{self.name}  ({self.parent})"
        return self.name

    def matches(self, needle: str) -> bool:
        """True when ``needle`` appears in anything a user would search on.

        Matching is case-insensitive over the name, the qualified name, the kind
        and the parent, so "orders" finds the table, "index" finds every index,
        and "sales.orders" finds it by its qualified name.
        """
        if not needle:
            return True
        lowered = needle.strip().lower()
        if not lowered:
            return True
        haystack = " ".join(
            (
                self.name,
                self.qualified_name,
                self.kind.value,
                self.parent,
                self.connection_name,
                self.detail,
            )
        ).lower()
        return lowered in haystack


@dataclass
class Catalog:
    """An index of objects, grouped and searchable."""

    objects: list[ObjectRef] = field(default_factory=list)
    #: Databases the index was built from, so the UI can show coverage.
    databases: list[tuple[str, str]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.objects)

    def __iter__(self):
        return iter(self.objects)

    def __bool__(self) -> bool:
        return bool(self.objects)

    def add(self, obj: ObjectRef) -> None:
        self.objects.append(obj)

    def add_all(self, objects: Iterable[ObjectRef]) -> None:
        self.objects.extend(objects)

    def by_kind(self, kind: ObjectKind | None = None) -> dict[ObjectKind, list[ObjectRef]]:
        """Group objects by kind, in :data:`KIND_ORDER`.

        Empty kinds are omitted so the tree does not show a category that has
        nothing under it.
        """
        grouped: dict[ObjectKind, list[ObjectRef]] = {}
        for obj in self.objects:
            if kind is not None and obj.kind is not kind:
                continue
            grouped.setdefault(obj.kind, []).append(obj)
        for items in grouped.values():
            items.sort(key=lambda o: (o.database, o.parent, o.name))
        return {k: grouped[k] for k in KIND_ORDER if k in grouped}

    def search(self, query: str, *, limit: int = 500) -> list[ObjectRef]:
        """Objects whose name (or kind, or parent) contains ``query``.

        A blank query returns nothing rather than everything: the caller is a
        search box, and dumping the whole catalog on focus would be useless.
        """
        if not query or not query.strip():
            return []
        hits = [obj for obj in self.objects if obj.matches(query)]
        hits.sort(key=lambda o: (o.kind is not ObjectKind.TABLE, o.database, o.name))
        return hits[:limit]

    def counts(self) -> dict[str, int]:
        """Object count per kind, for a summary label."""
        out: dict[str, int] = {}
        for obj in self.objects:
            out[obj.kind.value] = out.get(obj.kind.value, 0) + 1
        return out

    def summary(self) -> str:
        """One-line description of what the index covers."""
        if not self.objects:
            return "no objects"
        counts = self.counts()
        parts = [f"{n} {kind}{'s' if n != 1 else ''}" for kind, n in sorted(counts.items())]
        scope = f"{len(self.databases)} database(s)" if self.databases else "no database"
        return f"{', '.join(parts)} across {scope}"


# ---- building an index from a connector ----

#: Kinds a driver can list directly, mapped to its method name.
LIST_METHODS: dict[ObjectKind, str] = {
    ObjectKind.TABLE: "list_tables",
    ObjectKind.VIEW: "list_views",
    ObjectKind.TRIGGER: "list_triggers",
}


def _routine_kind(routine_type: str) -> ObjectKind:
    """Map a driver's routine type onto procedure vs function."""
    text = (routine_type or "").strip().lower()
    if "function" in text or text in ("func", "f"):
        return ObjectKind.FUNCTION
    return ObjectKind.PROCEDURE


def objects_from_routines(
    routines: Sequence[tuple[str, str]],
    *,
    connection_id: str = "",
    connection_name: str = "",
    database: str = "",
) -> list[ObjectRef]:
    """Turn ``list_routines`` output into catalogue entries.

    Drivers report a type alongside the name; procedures and functions are kept
    distinct so the tree can show them separately, which is how every DBA tool
    presents them.
    """
    out: list[ObjectRef] = []
    for name, routine_type in routines:
        out.append(
            ObjectRef(
                kind=_routine_kind(routine_type),
                name=str(name),
                connection_id=connection_id,
                connection_name=connection_name,
                database=database,
                detail=str(routine_type or ""),
            )
        )
    return out


def objects_from_triggers(
    triggers: Sequence[tuple[str, str]],
    *,
    connection_id: str = "",
    connection_name: str = "",
    database: str = "",
) -> list[ObjectRef]:
    """Turn ``list_triggers`` output into catalogue entries.

    Each entry is ``(trigger_name, table_name)``; the table goes in ``parent`` so
    the tree can show which table a trigger belongs to.
    """
    return [
        ObjectRef(
            kind=ObjectKind.TRIGGER,
            name=str(name),
            parent=str(table or ""),
            connection_id=connection_id,
            connection_name=connection_name,
            database=database,
        )
        for name, table in triggers
    ]


def objects_from_names(
    names: Sequence[str],
    kind: ObjectKind,
    *,
    connection_id: str = "",
    connection_name: str = "",
    database: str = "",
) -> list[ObjectRef]:
    """Turn a plain name listing into catalogue entries."""
    return [
        ObjectRef(
            kind=kind,
            name=str(name),
            connection_id=connection_id,
            connection_name=connection_name,
            database=database,
        )
        for name in names
    ]


def objects_from_table_info(
    table_info,
    *,
    connection_id: str = "",
    connection_name: str = "",
    database: str = "",
) -> list[ObjectRef]:
    """Catalogue a table's indexes, constraints and columns.

    ``get_table_info`` already reads all three, so browsing them costs no extra
    round trip per object.
    """
    out: list[ObjectRef] = []
    table = getattr(table_info, "name", "")

    for index in getattr(table_info, "indexes", []) or []:
        columns = ", ".join(getattr(index, "columns", []) or [])
        out.append(
            ObjectRef(
                kind=ObjectKind.INDEX,
                name=getattr(index, "name", ""),
                parent=table,
                connection_id=connection_id,
                connection_name=connection_name,
                database=database,
                detail=columns,
            )
        )

    for fk in getattr(table_info, "foreign_keys", []) or []:
        target = getattr(fk, "ref_table", "")
        column = getattr(fk, "column", "")
        out.append(
            ObjectRef(
                kind=ObjectKind.CONSTRAINT,
                name=getattr(fk, "name", ""),
                parent=table,
                connection_id=connection_id,
                connection_name=connection_name,
                database=database,
                detail=f"{column} -> {target}",
            )
        )

    for column in getattr(table_info, "columns", []) or []:
        out.append(
            ObjectRef(
                kind=ObjectKind.COLUMN,
                name=getattr(column, "name", ""),
                parent=table,
                connection_id=connection_id,
                connection_name=connection_name,
                database=database,
                detail=getattr(column, "data_type", ""),
            )
        )

    return out


def search_across(catalogs: Iterable[tuple[str, Catalog]], query: str, *, limit: int = 500):
    """Search several connections' catalogs at once.

    ``catalogs`` pairs a connection name with its index.  Results stay grouped by
    connection so the UI can show "found in Production" rather than a flat list
    of identically named tables.
    """
    if not query or not query.strip():
        return {}
    results: dict[str, list[ObjectRef]] = {}
    for name, catalog in catalogs:
        hits = catalog.search(query, limit=limit)
        if hits:
            results[name] = hits
    return results
