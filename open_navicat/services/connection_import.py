"""Import connection profiles from DBeaver / Navicat configuration files.

DBeaver stores its connections in an open JSON layout
(``data-sources.json``, workspace or project flavour) — that is the primary,
fully supported source here.  Navicat's ``.ncx`` export and the Windows
registry are parsed best-effort: everything except the password is plain
text there, so host/port/user/database import cleanly while the encrypted
password is left blank on purpose.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from open_navicat.drivers.registry import get_spec, is_file_engine, normalize_engine
from open_navicat.models.connection import ConnectionInfo

#: DBeaver/Navicat provider names mapped onto our engine slugs.
PROVIDER_ALIASES: dict[str, str] = {
    "mysql": "mysql",
    "mysql8": "mysql",
    "mariadb": "mysql",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "postgres-jdbc": "postgresql",
    "redshift": "postgresql",
    "sqlserver": "sqlserver",
    "mssql": "sqlserver",
    "sql-server": "sqlserver",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
    "mongodb": "mongodb",
    "mongo": "mongodb",
    "redis": "redis",
    "clickhouse": "clickhouse",
    "oracle": "oracle",
}

#: Navicat connection-type strings found in .ncx files / registry subkeys.
NAVICAT_TYPE_ALIASES: dict[str, str] = {
    "mysql": "mysql",
    "mysql8": "mysql",
    "mariadb": "mysql",
    "pgsql": "postgresql",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "mssql": "sqlserver",
    "sqlserver": "sqlserver",
    "sqlserver-azure": "sqlserver",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
    "mongodb": "mongodb",
    "mongo": "mongodb",
    "redis": "redis",
    "clickhouse": "clickhouse",
    "oracle": "oracle",
}

#: Registry subkeys that are never connection entries.
_REGISTRY_NOISE = ("Servers", "Connection", "Connections")


def resolve_engine(provider: str, *, aliases: dict[str, str]) -> str | None:
    """Map an external provider name onto an engine slug, or None if unknown."""
    if not provider:
        return None
    slug = normalize_engine(provider)
    return aliases.get(slug.lower())


def _port(value: object, engine: str) -> int:
    """Coerce a port that may be str/int/empty, falling back to the default."""
    if value in (None, ""):
        return get_spec(engine).default_port
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return get_spec(engine).default_port


def _text(value: object) -> str:
    return str(value).strip() if value not in (None, "") else ""


@dataclass
class ImportedConnection:
    """One connection parsed from an external tool's configuration."""

    engine: str
    name: str
    host: str = ""
    port: int = 0
    user: str = ""
    password: str = ""
    database: str = ""
    options: dict[str, str] = field(default_factory=dict)
    source: str = ""
    note: str = ""

    def to_connection_info(self) -> ConnectionInfo:
        """Build a ConnectionInfo, honouring file-based engine quirks."""
        spec = get_spec(self.engine)
        info = ConnectionInfo(
            name=self.name,
            engine=self.engine,
            host=self.host,
            port=self.port or spec.default_port,
            user=self.user,
            password=self.password,
            database=self.database,
        )
        if is_file_engine(self.engine):
            # File engines carry the path in ``database`` and must not keep a
            # leftover loopback host from the source tool.
            info.host = ""
            info.port = 0
        return info


@dataclass
class ImportSkip:
    """A source entry that could not be turned into a connection."""

    name: str
    reason: str


@dataclass
class ConnectionImportResult:
    """Everything recovered from one source, plus what was refused."""

    source: str
    connections: list[ImportedConnection] = field(default_factory=list)
    skipped: list[ImportSkip] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.connections)

    def render(self) -> str:
        """Human-readable plan: one line per connection, then the skips."""
        lines = [f"{len(self.connections)} connection(s) from {self.source}:"] + [
            f"  [{i.engine}] {i.name} {i.host or '(file)'}"
            f"{':' + str(i.port) if i.port else ''}/{i.database}"
            + (f"  -- {i.note}" if i.note else "")
            for i in self.connections
        ]
        lines += [f"  skipped: {s.name} ({s.reason})" for s in self.skipped]
        return "\n".join(lines)


def _imported_from_dbeaver(
    entry: dict, tunnels: dict[str, dict]
) -> tuple[ImportedConnection | None, ImportSkip | None]:
    """Turn one DBeaver ``connections`` entry into our model."""
    raw_name = str(entry.get("name") or "").strip()
    provider = str(entry.get("provider") or entry.get("driver") or "").strip()
    engine = resolve_engine(provider, aliases=PROVIDER_ALIASES)
    if engine is None:
        return None, ImportSkip(raw_name or provider or "(unnamed)", f"unknown provider '{provider}'")
    if get_spec(engine) is None:  # pragma: no cover - resolve_engine is filtered
        return None, ImportSkip(raw_name, f"engine '{engine}' not supported")

    conf = entry.get("configuration") or {}
    options = {
        k: str(v)
        for k, v in sorted(conf.items())
        if k not in ("host", "port", "database", "user", "password")
        and v not in (None, "")
    }
    message_parts = []
    tunnel_ref = _text(conf.get("tunnel"))
    if tunnel_ref:
        options["tunnel"] = tunnel_ref
        if tunnel_ref not in tunnels:
            options["tunnel_note"] = "referenced tunnel definition is missing from this file"
        message_parts.append("SSH tunnel not imported - set it up again in the connection dialog")
    if not _text(conf.get("password")) and not is_file_engine(engine):
        message_parts.append("password not stored in the source file - fill it in")

    return (
        ImportedConnection(
            engine=engine,
            name=raw_name or f"{engine}@{_text(conf.get('host')) or '(local)'}",
            host=_text(conf.get("host")),
            port=_port(conf.get("port"), engine),
            user=_text(conf.get("user")),
            password=_text(conf.get("password")),
            database=_text(conf.get("database")),
            options=options,
            source="dbeaver",
            note="; ".join(message_parts),
        ),
        None,
    )


def parse_dbeaver(path: str | Path) -> ConnectionImportResult:
    """Parse DBeaver ``data-sources.json`` (workspace or project layout)."""
    file = Path(path)
    data = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object at the top level")
    raw = data.get("connections") if "connections" in data else data.get("dataSources")
    if not isinstance(raw, dict):
        raise ValueError("no 'connections' or 'dataSources' section found - is this a DBeaver file?")
    tunnels = data.get("tunnels") or {}
    result = ConnectionImportResult(source=str(file))
    for key in sorted(raw):
        item, skip = _imported_from_dbeaver(raw[key] or {}, tunnels if isinstance(tunnels, dict) else {})
        if item is not None:
            result.connections.append(item)
        elif skip is not None:
            result.skipped.append(skip)
    return result


def _local(tag: object) -> str:
    """Tag/attribute name without XML namespace, lower-cased."""
    text = tag if isinstance(tag, str) else ""
    return text.rsplit("}", 1)[-1].lower()


def _navicat_entry(element: ElementTree.Element) -> tuple[ImportedConnection | None, ImportSkip | None]:
    """Read one Navicat ``<Connection>`` element, tolerating name variants."""
    fields: dict[str, str] = {}
    for key, value in element.attrib.items():
        fields[_local(key)] = str(value or "").strip()
    for child in element:
        text = (child.text or "").strip()
        if text:
            fields[_local(child.tag)] = text
    conn_type = (
        fields.get("conntype")
        or fields.get("connectiontype")
        or fields.get("type")
        or fields.get("conn_type")
        or ""
    )
    engine = resolve_engine(conn_type, aliases=NAVICAT_TYPE_ALIASES)
    name = fields.get("name") or fields.get("connectionname") or ""
    if engine is None:
        return None, ImportSkip(name or conn_type or "(unnamed)", f"unknown type '{conn_type}'")
    host = fields.get("host") or fields.get("hostname") or ""
    database = fields.get("database") or fields.get("dbname") or ""
    if not host and not database:
        return None, ImportSkip(name, "no host and no database in this entry")
    options = {
        k: v
        for k, v in sorted(fields.items())
        if k not in ("host", "hostname", "port", "username", "user", "database",
                     "dbname", "password", "name", "connectionname")
        and v
    }
    return (
        ImportedConnection(
            engine=engine,
            name=name or f"{engine}@{host or '(file)'}",
            host=host,
            port=_port(fields.get("port"), engine),
            user=fields.get("username") or fields.get("user") or "",
            password="",  # Navicat encrypts it; importing a broken blob is worse
            database=database,
            options=options,
            source="navicat",
            note="password not imported (encrypted by Navicat)",
        ),
        None,
    )


def parse_navicat_ncx(path: str | Path) -> ConnectionImportResult:
    """Best-effort parse of a Navicat ``.ncx`` export (XML flavour)."""
    file = Path(path)
    text = file.read_text(encoding="utf-8", errors="replace")
    if not text.lstrip().startswith("<"):
        raise ValueError(
            "not an XML Navicat export - Navicat .ncx files may be encrypted; "
            "passwords can never be recovered from them"
        )
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as err:
        raise ValueError(f"Navicat export is not well-formed XML: {err}") from err
    result = ConnectionImportResult(source=str(file))
    for element in root.iter():
        if _local(element.tag) == "connection":
            item, skip = _navicat_entry(element)
            if item is not None:
                result.connections.append(item)
            elif skip is not None:
                result.skipped.append(skip)
    return result


RegistryTree = dict[str, dict[str, str]]


def _load_registry_tree() -> RegistryTree:
    """Read HKCU\\Software\\PremiumSoft\\Navicat\\Servers (Windows only)."""
    try:
        import winreg
    except ImportError as exc:  # pragma: no cover - non-Windows
        raise ValueError("registry import needs Windows") from exc
    tree: RegistryTree = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\PremiumSoft\Navicat\Servers") as root:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if sub.lower() in _REGISTRY_NOISE:
                    continue
                values: dict[str, str] = {}
                with winreg.OpenKey(root, sub) as handle:
                    j = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(handle, j)
                        except OSError:
                            break
                        j += 1
                        if isinstance(value, str):
                            values[name.lower()] = value
                tree[sub] = values
    except FileNotFoundError as exc:
        raise ValueError("Navicat registry entries not found") from exc
    return tree


def _registry_entry(sub: str, values: dict[str, str]) -> tuple[ImportedConnection | None, ImportSkip | None]:
    """Registry subkeys look like ``MySQL_1`` with flat Host/Port/UserName values."""
    provider = sub.rsplit("_", 1)[0]
    engine = resolve_engine(provider, aliases=NAVICAT_TYPE_ALIASES)
    name = sub
    if engine is None:
        return None, ImportSkip(name, f"unknown type '{provider}'")
    host = values.get("host") or ""
    database = values.get("database") or ""
    if not host and not database:
        return None, ImportSkip(name, "no host and no database")
    options = {
        k: v
        for k, v in sorted(values.items())
        if k not in ("host", "port", "username", "user", "database", "password",
                     "name", "connectionname")
        and v
    }
    return (
        ImportedConnection(
            engine=engine,
            name=name,
            host=host,
            port=_port(values.get("port"), engine),
            user=values.get("username") or values.get("user") or "",
            password="",  # encrypted in the registry as well
            database=database,
            options=options,
            source="navicat-registry",
            note="password not imported (encrypted by Navicat)",
        ),
        None,
    )


def read_navicat_registry(tree: RegistryTree | None = None) -> ConnectionImportResult:
    """Import Navicat connections from the Windows registry."""
    if tree is None:
        tree = _load_registry_tree()
    result = ConnectionImportResult(source="navicat-registry")
    for sub in sorted(tree):
        item, skip = _registry_entry(sub, tree[sub])
        if item is not None:
            result.connections.append(item)
        elif skip is not None:
            result.skipped.append(skip)
    return result


def import_file(path: str | Path) -> ConnectionImportResult:
    """Import from a DBeaver or Navicat file, sniffing the layout by content."""
    file = Path(path)
    head = file.read_text(encoding="utf-8", errors="replace").lstrip()[:1]
    if head == "{":
        return parse_dbeaver(file)
    if head == "<":
        return parse_navicat_ncx(file)
    raise ValueError(f"unrecognised connection-export format in {file.name}")


def find_duplicates(
    imported: Iterable[ImportedConnection], existing: list[ConnectionInfo]
) -> dict[int, ConnectionInfo]:
    """Map imported entries to an existing profile when they look identical.

    A duplicate is the same engine + host + port + database + user, or a
    profile that already carries the same name.  Returning indices (not
    objects) keeps callers honest about which side they match on.
    """
    dupes: dict[int, ConnectionInfo] = {}
    for index, item in enumerate(imported):
        for other in existing:
            same_target = (
                item.engine == other.engine
                and item.host == other.host
                and item.port == other.port
                and item.database == other.database
                and item.user == other.user
            )
            if same_target or (item.name and item.name == other.name):
                dupes[index] = other
                break
    return dupes


@dataclass
class SaveOutcome:
    """What happened to one imported connection."""

    connection: ImportedConnection
    status: str  # "saved" | "duplicate" | "failed"
    detail: str = ""


def save_imported(
    connections: list[ImportedConnection],
    *,
    existing: list[ConnectionInfo] | None = None,
    dry_run: bool = False,
) -> list[SaveOutcome]:
    """Persist imported connections, skipping duplicates.  Returns per-item outcomes."""
    from open_navicat.dal.local_config import local_db

    if existing is None:
        existing = local_db.list_connections()
    dupes = find_duplicates(connections, existing)
    outcomes: list[SaveOutcome] = []
    for index, item in enumerate(connections):
        if index in dupes:
            outcomes.append(
                SaveOutcome(item, "duplicate", f"already configured as '{dupes[index].name}'")
            )
            continue
        if dry_run:
            outcomes.append(SaveOutcome(item, "saved", "would be saved"))
            continue
        try:
            info = item.to_connection_info()
            local_db.save_connection(info)
        except Exception as exc:  # noqa: BLE001 - report, keep importing the rest
            outcomes.append(SaveOutcome(item, "failed", str(exc)))
        else:
            outcomes.append(SaveOutcome(item, "saved", info.id))
    return outcomes


def render_outcomes(outcomes: list[SaveOutcome]) -> str:
    """One status line per outcome for the CLI/GUI result display."""
    return "\n".join(
        f"  {o.status:<9} [{o.connection.engine}] {o.connection.name}: {o.detail}"
        for o in outcomes
    )
