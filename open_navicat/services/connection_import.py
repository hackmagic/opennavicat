"""Import connection profiles from other database tools' configuration files.

Six sources are supported, all parsed offline from the files the other tool
writes — nothing is executed and no network call is made:

===================  ===================================================
format key           source
===================  ===================================================
``dbx``              DBX ``.dbx`` export (plain JSON or AES-256-GCM)
``navicat``          Navicat ``.ncx`` export / Windows registry
``dbeaver``          DBeaver ``data-sources.json`` (workspace + project)
``datagrip``         DataGrip / IntelliJ ``dataSources.xml``
``rdm``              RedisDesktopManager JSON export
``another_rdm``      Another Redis Desktop Manager ``.ano`` export
===================  ===================================================

A single honest rule runs through all six parsers: **another tool's encrypted
passwords are never recovered**.  DBX is the one exception, because it exports
its own passphrase-encrypted file with a published AES-256-GCM + PBKDF2
envelope, so a passphrase the user already knows really is enough.  Everywhere
else the credential is left blank and a ``note`` says so, rather than importing
a blob that would fail authentication later with a confusing error.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
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

#: DataGrip ``<driver-ref>`` prefixes mapped onto our engine slugs.
DATAGRIP_DRIVER_ALIASES: dict[str, str] = {
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
    "sqlserver": "sqlserver",
    "mssql": "sqlserver",
    "jtds": "sqlserver",
    "oracle": "oracle",
    "clickhouse": "clickhouse",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "redis": "redis",
}

#: JDBC subprotocol → engine, the fallback when ``<driver-ref>`` is absent.
DATAGRIP_SUBPROTOCOL_ALIASES: dict[str, str] = {
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgresql": "postgresql",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
    "sqlserver": "sqlserver",
    "jtds": "sqlserver",
    "oracle": "oracle",
    "clickhouse": "clickhouse",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "redis": "redis",
}

#: DBX ``db_type`` strings mapped onto our engine slugs.
DBX_TYPE_ALIASES: dict[str, str] = {
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "cockroachdb": "postgresql",
    "redshift": "postgresql",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
    "sqlserver": "sqlserver",
    "mssql": "sqlserver",
    "oracle": "oracle",
    "clickhouse": "clickhouse",
    "mongodb": "mongodb",
    "mongo": "mongodb",
    "redis": "redis",
}

#: Registry subkeys that are never connection entries.
_REGISTRY_NOISE = ("Servers", "Connection", "Connections")

#: PBKDF2 rounds DBX uses for a passphrase-protected config export.
_DBX_KDF_ITERATIONS = 100_000


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


def _flag(value: object) -> bool:
    """Coerce the several truthy spellings other tools use into a bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "on")


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
    # ---- grouping (DataGrip folders, RDM/Another-RDM groups) ----
    group: str = ""
    # ---- SSH tunnel carried over when the source tool had one ----
    use_ssh: bool = False
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_password: str = ""
    ssh_key_file: str = ""
    # ---- TLS material carried over as paths, never copied ----
    use_ssl: bool = False
    ssl_ca: str = ""
    ssl_cert: str = ""
    ssl_key: str = ""

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
            group=self.group,
            use_ssh=self.use_ssh,
            ssh_host=self.ssh_host,
            ssh_port=self.ssh_port or 22,
            ssh_user=self.ssh_user,
            ssh_password=self.ssh_password,
            ssh_key_file=self.ssh_key_file,
            use_ssl=self.use_ssl,
            ssl_ca=self.ssl_ca,
            ssl_cert=self.ssl_cert,
            ssl_key=self.ssl_key,
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
    #: Format key that produced this result (``dbeaver``, ``datagrip``, ...).
    format: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.connections)

    def render(self) -> str:
        """Human-readable plan: one line per connection, then the skips."""
        lines = [f"{len(self.connections)} connection(s) from {self.source}:"] + [
            f"  [{i.engine}] {i.name} {i.host or '(file)'}"
            f"{':' + str(i.port) if i.port else ''}/{i.database or '(no db)'}"
            + (f"  [{i.group}]" if i.group else "")
            + (f"  -- {i.note}" if i.note else "")
            for i in self.connections
        ]
        lines += [f"  skipped: {s.name} ({s.reason})" for s in self.skipped]
        return "\n".join(lines)


# ── DBeaver ────────────────────────────────────────────────────────────────


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
            group=_text(entry.get("folder") or entry.get("group")),
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
    result = ConnectionImportResult(source=str(file), format="dbeaver")
    for key in sorted(raw):
        item, skip = _imported_from_dbeaver(raw[key] or {}, tunnels if isinstance(tunnels, dict) else {})
        if item is not None:
            result.connections.append(item)
        elif skip is not None:
            result.skipped.append(skip)
    return result


# ── Navicat ────────────────────────────────────────────────────────────────


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
    result = ConnectionImportResult(source=str(file), format="navicat")
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
    result = ConnectionImportResult(source="navicat-registry", format="navicat")
    for sub in sorted(tree):
        item, skip = _registry_entry(sub, tree[sub])
        if item is not None:
            result.connections.append(item)
        elif skip is not None:
            result.skipped.append(skip)
    return result


# ── DataGrip ───────────────────────────────────────────────────────────────

#: ``jdbc:<subprotocol>:`` then whatever follows, captured separately per shape.
_JDBC_PREFIX = re.compile(r"^jdbc:([a-zA-Z0-9]+):", re.IGNORECASE)
#: ``//host[:port][/database]`` tail used by most JDBC drivers.
_JDBC_SERVER = re.compile(
    r"^//(?P<host>\[[^\]]+\]|[^/:;?]+)(?::(?P<port>\d+))?(?:/(?P<database>[^?;]*))?",
)
#: Oracle's two legacy shapes: ``@host:port:sid`` and ``@//host:port/service``.
#: Both may carry a driver subtype first (``jdbc:oracle:thin:@...``).
_JDBC_ORACLE_SID = re.compile(
    r"^(?:[a-z]+:)?@?(?P<host>[^/:@;]+):(?P<port>\d+):(?P<database>[^?;]+)$", re.IGNORECASE
)
_JDBC_ORACLE_SERVICE = re.compile(
    r"^(?:[a-z]+:)?@?//(?P<host>\[[^\]]+\]|[^/:;]+)(?::(?P<port>\d+))?/(?P<database>[^?;]+)$",
    re.IGNORECASE,
)
#: SQL Server's ``//host:port;key=value`` form.
_JDBC_SQLSERVER_DB = re.compile(r"[;?&]databaseName=([^;&?]+)", re.IGNORECASE)


def _datagrip_sibling(path: Path, name: str) -> Path | None:
    """Find a sibling config file case-insensitively, or None."""
    try:
        for entry in path.parent.iterdir():
            if entry.name.lower() == name.lower() and entry.is_file():
                return entry
    except OSError:  # pragma: no cover - unreadable directory
        return None
    return None


def _jdbc_parts(url: str) -> dict[str, str]:
    """Split a JDBC URL into host/port/database plus any embedded credentials."""
    raw = url.strip()
    match = _JDBC_PREFIX.match(raw)
    remainder = raw[match.end():] if match else raw
    parts: dict[str, str] = {"subprotocol": match.group(1).lower() if match else ""}

    oracle = _JDBC_ORACLE_SID.match(remainder) or _JDBC_ORACLE_SERVICE.match(remainder)
    if oracle:
        parts["host"] = oracle.group("host")
        parts["port"] = oracle.group("port") or ""
        parts["database"] = oracle.group("database").strip()
    else:
        server = _JDBC_SERVER.match(remainder)
        if server:
            parts["host"] = server.group("host")
            parts["port"] = server.group("port") or ""
            database = (server.group("database") or "").strip()
            if not database:
                sqlserver = _JDBC_SQLSERVER_DB.search(remainder)
                if sqlserver:
                    database = sqlserver.group(1).strip()
            parts["database"] = database
        elif remainder and not remainder.startswith("//"):
            # SQLite/DuckDB put a bare file path after the subprotocol.
            parts["database"] = remainder.split(";")[0].split("?")[0].strip()

    query = remainder.split("?", 1)[1] if "?" in remainder else ""
    for pair in query.split("&"):
        key, _, value = pair.partition("=")
        if key.lower() in ("user", "username", "password") and value:
            parts[key.lower()] = _unquote(value)
    return parts


def _unquote(value: str) -> str:
    """Percent-decode a fragment, keeping literal ``%`` sequences intact."""
    from urllib.parse import unquote

    return unquote(value)


def _expand_home(value: str) -> str:
    """Expand DataGrip's ``$USER_HOME$`` macro into this machine's home path.

    The macro is DataGrip's own convention for "the importing user's home", so
    substituting ours is the only reading that keeps a SQLite path usable.  A
    path from another machine may still be wrong; the user can correct it in the
    connection dialog, which beats importing a literal ``$USER_HOME$``.
    """
    if "$USER_HOME$" not in value:
        return value
    return value.replace("$USER_HOME$", str(Path.home()))


def _datagrip_engine(fragment: dict[str, str]) -> tuple[str | None, str]:
    """Pick an engine from driver-ref, then subprotocol, then the product name.

    Returns ``(engine, how)`` so a refusal can name what was actually inspected
    instead of guessing.  Custom drivers (no ``<driver-ref>``) are only kept
    when the URL or product still identifies a database we drive.
    """
    for source, aliases, key in (
        ("driver-ref", DATAGRIP_DRIVER_ALIASES, fragment.get("driver_ref", "")),
        ("subprotocol", DATAGRIP_SUBPROTOCOL_ALIASES, fragment.get("subprotocol", "")),
        ("product", DATAGRIP_DRIVER_ALIASES, fragment.get("product", "")),
    ):
        if not key:
            continue
        slug = normalize_engine(key)
        # driver-ref values look like "mysql" or "postgresql"; some builds emit
        # "mariadb" or "jtds-1.3", so try the whole value then its head.
        engine = aliases.get(slug) or aliases.get(slug.split("-", 1)[0])
        if engine:
            return engine, source
    return None, ""


def _parse_datagrip_sources(text: str) -> dict[str, dict[str, str]]:
    """Index ``dataSources.xml`` / ``dataSources.local.xml`` by data-source uuid."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as err:
        raise ValueError(f"DataGrip config is not well-formed XML: {err}") from err
    found: dict[str, dict[str, str]] = {}
    for element in root.iter():
        if _local(element.tag) != "data-source":
            continue
        uuid = element.attrib.get("uuid") or ""
        if not uuid:
            continue
        entry = found.setdefault(uuid, {})
        entry["name"] = element.attrib.get("name") or entry.get("name", "")
        # DataGrip keeps the folder as `group`, older builds used `group-name`.
        group = element.attrib.get("group") or element.attrib.get("group-name") or ""
        if group:
            entry["group"] = group
        for child in element.iter():
            tag = _local(child.tag)
            if tag == "database-info":
                # `<database-info product="PostgreSQL">` is the only product hint.
                product = child.attrib.get("product") or ""
                if product:
                    entry["product"] = product
                continue
            value = (child.text or "").strip()
            if not value:
                continue
            if tag == "driver-ref":
                entry["driver_ref"] = value
            elif tag == "jdbc-url":
                entry["jdbc_url"] = value
            elif tag in ("jdbc-driver", "driver-class"):
                entry["driver_class"] = value
            elif tag in ("user-name", "user"):
                entry["user"] = value
            elif tag == "password":
                entry["password"] = value
    return found


def parse_datagrip(path: str | Path, local_path: str | Path | None = None) -> ConnectionImportResult:
    """Parse DataGrip / IntelliJ ``dataSources.xml``.

    ``dataSources.local.xml`` (which carries user names and the product name)
    is used to fill in fields the shared file omits; it is auto-discovered
    beside ``dataSources.xml`` when not passed explicitly.
    """
    file = Path(path)
    shared = _parse_datagrip_sources(file.read_text(encoding="utf-8", errors="replace"))

    local_file = Path(local_path) if local_path else _datagrip_sibling(file, "dataSources.local.xml")
    local: dict[str, dict[str, str]] = {}
    if local_file is not None:
        try:
            local = _parse_datagrip_sources(local_file.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            local = {}

    result = ConnectionImportResult(source=str(file), format="datagrip")
    for uuid, shared_entry in sorted(shared.items()):
        merged = dict(shared_entry)
        # The local file wins on credentials/product, the shared file on the URL.
        for key, value in local.get(uuid, {}).items():
            if key in ("user", "password", "product", "group") or not merged.get(key):
                merged[key] = value

        name = merged.get("name") or uuid
        jdbc_url = merged.get("jdbc_url", "")
        if not jdbc_url:
            result.skipped.append(ImportSkip(name, "no JDBC URL in this data source"))
            continue
        parts = _jdbc_parts(jdbc_url)
        merged.update(
            {k: v for k, v in parts.items() if k != "subprotocol" and v}
        )
        merged["subprotocol"] = parts.get("subprotocol", "")

        engine, _how = _datagrip_engine(merged)
        if engine is None:
            result.skipped.append(
                ImportSkip(
                    name,
                    f"unsupported DataGrip driver '{merged.get('driver_ref') or merged.get('subprotocol') or 'unknown'}'",
                )
            )
            continue

        host = merged.get("host", "")
        database = _expand_home(merged.get("database", ""))
        if not host and not database:
            result.skipped.append(ImportSkip(name, "no host and no database in this data source"))
            continue
        result.connections.append(
            ImportedConnection(
                engine=engine,
                name=name,
                host=host,
                port=_port(merged.get("port"), engine),
                user=merged.get("user", ""),
                password=merged.get("password", ""),
                database=database,
                options={"jdbc_url": jdbc_url} if jdbc_url else {},
                source="datagrip",
                note="" if merged.get("password") else "password not available in these files - fill it in",
                group=merged.get("group", ""),
            )
        )
    return result


# ── RedisDesktopManager / Another Redis Desktop Manager ────────────────────


def _redis_entry(entry: dict, *, source: str) -> ImportedConnection:
    """Build a Redis connection from an RDM- or Another-RDM-shaped record."""
    host = _text(entry.get("host"))
    port = _port(entry.get("port"), "redis")
    name = _text(entry.get("name")) or f"{host}:{port}"
    return ImportedConnection(
        engine="redis",
        name=name,
        host=host,
        port=port,
        user=_text(entry.get("username")),
        password=_text(entry.get("auth")) or _text(entry.get("password")),
        database=_text(entry.get("db") or entry.get("namespace") or "0") or "0",
        source=source,
    )


def _redis_rdm_options(entry: dict, connection: ImportedConnection) -> None:
    """Carry RDM/Another-RDM TLS + SSH material across as paths, not copies."""
    if _flag(entry.get("ssl")):
        connection.use_ssl = True
        connection.ssl_ca = _text(entry.get("ssl_ca_cert_path"))
        connection.ssl_cert = _text(entry.get("ssl_local_cert_path") or entry.get("ssl_cert_path"))
        connection.ssl_key = _text(entry.get("ssl_private_key_path"))
    ssh_host = _text(entry.get("ssh_host"))
    if ssh_host:
        connection.use_ssh = True
        connection.ssh_host = ssh_host
        connection.ssh_port = _port(entry.get("ssh_port"), "redis") or 22
        connection.ssh_user = _text(entry.get("ssh_user"))
        connection.ssh_password = _text(entry.get("ssh_password"))
        connection.ssh_key_file = _text(entry.get("ssh_private_key_path"))
        connection.options["ssh_agent"] = "1" if _flag(entry.get("ssh_agent")) else ""


def parse_rdm(path: str | Path) -> ConnectionImportResult:
    """Parse a RedisDesktopManager JSON export (nested group tree)."""
    file = Path(path)
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"not JSON - is this a RedisDesktopManager export? ({err})") from err
    if not isinstance(data, list):
        raise ValueError("a RedisDesktopManager export is a JSON array of groups and connections")

    result = ConnectionImportResult(source=str(file), format="rdm")

    def walk(items: list, path_parts: list[str], depth: int) -> None:
        if depth > 32:
            result.skipped.append(ImportSkip("/".join(path_parts) or "(root)", "groups nested too deeply"))
            return
        for value in items:
            if not isinstance(value, dict):
                result.skipped.append(ImportSkip("/".join(path_parts) or "(root)", "entry is not an object"))
                continue
            kind = _text(value.get("type"))
            if kind == "group":
                name = _text(value.get("name"))
                nested = value.get("connections")
                if not isinstance(nested, list):
                    result.skipped.append(ImportSkip(name or "(unnamed group)", "group has no connections array"))
                    continue
                walk(nested, [*path_parts, name] if name else path_parts, depth + 1)
                continue
            if kind and kind != "connection":
                result.skipped.append(ImportSkip(_text(value.get("name")) or "(unnamed)", f"unsupported entry '{kind}'"))
                continue
            host = _text(value.get("host"))
            if not host:
                result.skipped.append(ImportSkip(_text(value.get("name")) or "(unnamed)", "no host in this entry"))
                continue
            try:
                connection = _redis_entry(value, source="rdm")
            except ValueError as err:
                result.skipped.append(ImportSkip(_text(value.get("name")) or host, str(err)))
                continue
            _redis_rdm_options(value, connection)
            connection.group = "/".join(path_parts)
            note = ""
            if not connection.password:
                note = "password not stored in the export - fill it in"
            connection.note = note
            result.connections.append(connection)

    walk(data, [], 0)
    return result


def _decode_ano(text: str) -> str:
    """Unwrap Another Redis Desktop Manager's Base64-wrapped UTF-8 JSON."""
    packed = re.sub(r"\s+", "", text)
    if not packed:
        raise ValueError("the .ano export is empty")
    if len(packed) % 4 != 0 or re.search(r"[^A-Za-z0-9+/=]", packed):
        raise ValueError("not a Base64 payload - is this an Another Redis Desktop Manager .ano export?")
    try:
        return base64.b64decode(packed, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as err:
        raise ValueError(f"the .ano payload is not Base64-encoded UTF-8 JSON ({err})") from err


def parse_another_rdm(path: str | Path) -> ConnectionImportResult:
    """Parse an Another Redis Desktop Manager ``.ano`` export."""
    file = Path(path)
    raw = file.read_text(encoding="utf-8", errors="replace")
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("the .ano export is larger than 16 MiB")
    # Some exports are saved as plain JSON; accept that instead of refusing.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = json.loads(_decode_ano(raw))
        except json.JSONDecodeError as err:
            raise ValueError(f"the .ano export does not contain JSON ({err})") from err

    if isinstance(data, list):
        entries: list = data
        groups: list = []
    elif isinstance(data, dict):
        entries = data.get("connections") or []
        groups = data.get("groups") or []
    else:
        raise ValueError("the .ano export must be a JSON array or an object with 'connections'")
    if not isinstance(entries, list) or not isinstance(groups, list):
        raise ValueError("the .ano export has no usable 'connections' / 'groups' arrays")

    group_names: dict[str, str] = {}
    for group in groups:
        if isinstance(group, dict):
            gid = _text(group.get("id"))
            gname = _text(group.get("name"))
            if gid and gname:
                group_names[gid] = gname

    result = ConnectionImportResult(source=str(file), format="another_rdm")
    for value in entries:
        if not isinstance(value, dict):
            result.skipped.append(ImportSkip("(unnamed)", "entry is not an object"))
            continue
        name = _text(value.get("name"))
        host = _text(value.get("host"))
        if not host:
            result.skipped.append(ImportSkip(name or "(unnamed)", "no host in this entry"))
            continue
        if value.get("natMap") and isinstance(value["natMap"], dict) and value["natMap"]:
            result.skipped.append(ImportSkip(name or host, "NAT mapping has no equivalent here"))
            continue
        connection = _redis_entry(value, source="another_rdm")
        ssl_options = value.get("sslOptions")
        if isinstance(ssl_options, dict):
            connection.use_ssl = True
            connection.ssl_ca = _text(ssl_options.get("ca"))
            connection.ssl_cert = _text(ssl_options.get("cert"))
            connection.ssl_key = _text(ssl_options.get("key"))
        ssh_options = value.get("sshOptions")
        if isinstance(ssh_options, dict):
            ssh_host = _text(ssh_options.get("host"))
            if ssh_host:
                connection.use_ssh = True
                connection.ssh_host = ssh_host
                connection.ssh_port = _port(ssh_options.get("port"), "redis") or 22
                connection.ssh_user = _text(ssh_options.get("username"))
                connection.ssh_password = _text(ssh_options.get("password"))
                connection.ssh_key_file = _text(ssh_options.get("privatekey"))
        connection.group = group_names.get(_text(value.get("groupId")), "")
        mode = "cluster" if _flag(value.get("cluster")) else (
            "sentinel" if isinstance(value.get("sentinelOptions"), dict) else "standalone"
        )
        if mode != "standalone":
            connection.options["redis_mode"] = mode
        if not connection.password:
            connection.note = "password not stored in the export - fill it in"
        result.connections.append(connection)
    return result


# ── DBX ────────────────────────────────────────────────────────────────────


def _b64decode(value: object, label: str) -> bytes:
    try:
        return base64.b64decode(str(value), validate=True)
    except (ValueError, TypeError) as err:
        raise ValueError(f"the DBX export has an invalid '{label}' field ({err})") from err


def decrypt_dbx_payload(payload: dict, passphrase: str) -> str:
    """Decrypt a DBX ``dbx-encrypted`` envelope into its plaintext JSON.

    DBX derives an AES-256 key with PBKDF2-HMAC-SHA256 (100k rounds) over a
    16-byte salt and decrypts with AES-GCM over a 12-byte IV.  Those parameters
    are published in DBX's own export format, so a passphrase the user already
    knows is genuinely sufficient here — unlike Navicat/RDM credentials.
    """
    if not passphrase:
        raise ValueError("this DBX export is encrypted - a passphrase is required to read it")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError as exc:  # pragma: no cover - cryptography is a hard dependency
        raise ValueError("decrypting a DBX export needs the 'cryptography' package") from exc

    salt = _b64decode(payload.get("salt"), "salt")
    iv = _b64decode(payload.get("iv"), "iv")
    ciphertext = _b64decode(payload.get("data"), "data")
    key = PBKDF2HMAC(
        algorithm=SHA256(), length=32, salt=salt, iterations=_DBX_KDF_ITERATIONS
    ).derive(passphrase.encode("utf-8"))
    try:
        plaintext = AESGCM(key).decrypt(iv, ciphertext, None)
    except Exception as exc:  # noqa: BLE001 - AES-GCM reports every failure alike
        raise ValueError("wrong passphrase, or the DBX export is corrupted") from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError("the decrypted DBX payload is not UTF-8 JSON") from exc


def _dbx_connection(entry: dict, groups: dict[str, str]) -> tuple[ImportedConnection | None, ImportSkip | None]:
    """Turn one DBX connection record into our model."""
    name = _text(entry.get("name"))
    db_type = _text(entry.get("db_type") or entry.get("dbType") or entry.get("type"))
    engine = resolve_engine(db_type, aliases=DBX_TYPE_ALIASES)
    if engine is None:
        return None, ImportSkip(name or db_type or "(unnamed)", f"unknown database type '{db_type}'")

    host = _text(entry.get("host"))
    database = _text(entry.get("database") or entry.get("db") or "")
    if is_file_engine(engine):
        # A file engine keeps the path in `database`; DBX may also send it as
        # `file_path` or inside the connection string.
        database = _text(
            entry.get("file_path")
            or entry.get("database")
            or entry.get("database_name")
            or entry.get("path")
        )
    if not host and not database:
        return None, ImportSkip(name, "no host and no database in this entry")

    group = _text(entry.get("group") or entry.get("group_name"))
    if not group:
        group = groups.get(_text(entry.get("group_id")), "")

    connection = ImportedConnection(
        engine=engine,
        name=name or f"{engine}@{host or '(file)'}",
        host=host,
        port=_port(entry.get("port"), engine),
        user=_text(entry.get("username") or entry.get("user")),
        password=_text(entry.get("password")),
        database=database,
        source="dbx",
        group=group,
    )
    if _flag(entry.get("ssl")):
        connection.use_ssl = True
        connection.ssl_ca = _text(entry.get("ca_cert_path"))
        connection.ssl_cert = _text(entry.get("client_cert_path"))
        connection.ssl_key = _text(entry.get("client_key_path"))
    layers = entry.get("transport_layers") or entry.get("transportLayers") or []
    if isinstance(layers, list):
        for layer in layers:
            if not isinstance(layer, dict) or _text(layer.get("type")) != "ssh":
                continue
            ssh_host = _text(layer.get("host"))
            if not ssh_host:
                continue
            connection.use_ssh = True
            connection.ssh_host = ssh_host
            connection.ssh_port = _port(layer.get("port"), "redis") or 22
            connection.ssh_user = _text(layer.get("user"))
            connection.ssh_password = _text(layer.get("password"))
            connection.ssh_key_file = _text(layer.get("key_path"))
            break
    if not connection.password and not is_file_engine(engine):
        connection.note = "password not in this export - fill it in"
    return connection, None


def parse_dbx(path: str | Path, passphrase: str = "") -> ConnectionImportResult:
    """Parse a DBX ``.dbx`` config export, plain or passphrase-encrypted."""
    file = Path(path)
    raw = file.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ValueError(f"not a JSON DBX export ({err})") from err
    if not isinstance(data, dict):
        raise ValueError("a DBX export is a JSON object")

    envelope = _text(data.get("format"))
    if envelope == "dbx-encrypted":
        data = json.loads(decrypt_dbx_payload(data, passphrase))
        if not isinstance(data, dict):
            raise ValueError("the decrypted DBX payload is not a JSON object")
    elif envelope and envelope != "dbx-config":
        raise ValueError(f"unexpected DBX export format '{envelope}'")

    entries = data.get("connections")
    if not isinstance(entries, list):
        raise ValueError("no 'connections' array found - is this a DBX export?")

    groups: dict[str, str] = {}
    layout = data.get("layout")
    if isinstance(layout, dict):
        for group in layout.get("groups") or []:
            if isinstance(group, dict):
                gid = _text(group.get("id"))
                gname = _text(group.get("name"))
                if gid and gname:
                    groups[gid] = gname

    result = ConnectionImportResult(source=str(file), format="dbx")
    for value in entries:
        if not isinstance(value, dict):
            result.skipped.append(ImportSkip("(unnamed)", "entry is not an object"))
            continue
        item, skip = _dbx_connection(value, groups)
        if item is not None:
            result.connections.append(item)
        elif skip is not None:
            result.skipped.append(skip)
    return result


# ── OpenNavicat's own export ──────────────────────────────────────────────


def parse_opennavicat(path: str | Path) -> ConnectionImportResult:
    """Read back a profile exported by OpenNavicat itself.

    Two shapes exist in the wild: the original ``conn export``/GUI export, a
    bare object or array of ``ConnectionInfo`` fields with no engine, and the
    newer envelope that carries ``engine`` plus a ``format`` marker.  Both are
    accepted so an export from any past release still imports.
    """
    file = Path(path)
    data = json.loads(file.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "connections" in data:
        entries = data.get("connections")
    elif isinstance(data, list):
        entries = data
    else:
        entries = [data]
    if not isinstance(entries, list):
        raise ValueError("no 'connections' array found - is this an OpenNavicat export?")

    result = ConnectionImportResult(source=str(file), format="opennavicat")
    for value in entries:
        if not isinstance(value, dict):
            result.skipped.append(ImportSkip("(unnamed)", "entry is not an object"))
            continue
        name = _text(value.get("name"))
        engine = resolve_engine(_text(value.get("engine")) or "mysql", aliases=DBX_TYPE_ALIASES)
        if engine is None:
            result.skipped.append(
                ImportSkip(name or "(unnamed)", f"unknown engine '{value.get('engine')}'")
            )
            continue
        result.connections.append(
            ImportedConnection(
                engine=engine,
                name=name or "(unnamed)",
                host=_text(value.get("host")),
                port=_port(value.get("port"), engine),
                user=_text(value.get("user")),
                password=_text(value.get("password")),
                database=_text(value.get("database")),
                source="opennavicat",
                group=_text(value.get("group")),
                use_ssh=_flag(value.get("use_ssh")),
                ssh_host=_text(value.get("ssh_host")),
                ssh_port=_port(value.get("ssh_port"), "redis") or 22,
                ssh_user=_text(value.get("ssh_user")),
                ssh_password=_text(value.get("ssh_password")),
                ssh_key_file=_text(value.get("ssh_key_file")),
                use_ssl=_flag(value.get("use_ssl")),
                ssl_ca=_text(value.get("ssl_ca")),
                ssl_cert=_text(value.get("ssl_cert")),
                ssl_key=_text(value.get("ssl_key")),
            )
        )
    return result


def export_connections(
    connections: Iterable[ConnectionInfo], path: str | Path, *, include_passwords: bool = True
) -> int:
    """Write profiles to ``path`` in the format this importer reads back.

    Passwords are included by default because the file is the user's own
    migration artifact; callers that write somewhere shared can opt out.
    Returns how many connections were written.
    """
    rows = []
    for info in connections:
        row = {
            "name": info.name,
            "engine": info.engine,
            "host": info.host,
            "port": info.port,
            "user": info.user,
            "password": info.password if include_passwords else "",
            "database": info.database,
            "charset": info.charset,
            "use_ssh": info.use_ssh,
            "ssh_host": info.ssh_host,
            "ssh_port": info.ssh_port,
            "ssh_user": info.ssh_user,
            "ssh_password": info.ssh_password if include_passwords else "",
            "ssh_key_file": info.ssh_key_file,
            "use_ssl": info.use_ssl,
            "ssl_ca": info.ssl_ca,
            "ssl_cert": info.ssl_cert,
            "ssl_key": info.ssl_key,
            "color": info.color,
            "group": info.group,
        }
        rows.append(row)
    payload = {
        "format": "opennavicat-config",
        "version": 1,
        "connections": rows,
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return len(rows)


# ── Format registry + dispatch ─────────────────────────────────────────────


@dataclass(frozen=True)
class ImportFormat:
    """One supported source, as the CLI and GUI present it."""

    key: str
    extensions: tuple[str, ...]
    #: True when a passphrase may be needed to open the file at all.
    may_be_encrypted: bool = False


#: Every source we can read, in menu order.  `label` lives in i18n so the
#: service layer stays free of user-visible English.
IMPORT_FORMATS: tuple[ImportFormat, ...] = (
    ImportFormat("dbx", (".dbx", ".json"), may_be_encrypted=True),
    ImportFormat("navicat", (".ncx", ".xml")),
    ImportFormat("dbeaver", (".json", ".xml")),
    ImportFormat("datagrip", (".xml",)),
    ImportFormat("rdm", (".json",)),
    ImportFormat("another_rdm", (".ano", ".json", ".txt")),
)

FORMAT_KEYS: tuple[str, ...] = tuple(fmt.key for fmt in IMPORT_FORMATS)

_PARSERS: dict[str, Callable[..., ConnectionImportResult]] = {
    "dbx": parse_dbx,
    "navicat": parse_navicat_ncx,
    "dbeaver": parse_dbeaver,
    "datagrip": parse_datagrip,
    "rdm": parse_rdm,
    "another_rdm": parse_another_rdm,
    "opennavicat": parse_opennavicat,
}


def get_format(key: str) -> ImportFormat:
    """Return the format descriptor for ``key`` or raise a helpful ValueError."""
    for fmt in IMPORT_FORMATS:
        if fmt.key == key:
            return fmt
    raise ValueError(
        f"unknown import format '{key}'; supported formats: {', '.join(FORMAT_KEYS)}"
    )


def detect_format(path: str | Path) -> str:
    """Sniff which of the supported sources a file came from.

    Content beats extension: every tool reuses ``.json``/``.xml``, so the
    layout is the only reliable signal.
    """
    file = Path(path)
    text = file.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()
    if not stripped:
        raise ValueError(f"{file.name} is empty")

    if stripped.startswith("<"):
        try:
            root = ElementTree.fromstring(stripped)
        except ElementTree.ParseError as err:
            raise ValueError(f"{file.name} is not well-formed XML: {err}") from err
        tags = {_local(element.tag) for element in root.iter()}
        if "data-source" in tags:
            return "datagrip"
        if "connection" in tags:
            return "navicat"
        raise ValueError(f"unrecognised XML connection export in {file.name}")

    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as err:
            raise ValueError(f"{file.name} is not valid JSON: {err}") from err
        if isinstance(data, dict):
            envelope = _text(data.get("format"))
            if envelope in ("dbx-encrypted", "dbx-config"):
                return "dbx"
            if envelope == "opennavicat-config":
                return "opennavicat"
            if "connections" in data or "dataSources" in data:
                # DBX also uses `connections`, so tell them apart by the record
                # shape: DBX entries carry `db_type`, DBeaver entries `provider`.
                # DBeaver always keys `connections`/`dataSources` by id (a dict);
                # a list there is Another-RDM's `{connections, groups}` object.
                probe = data.get("connections") if "connections" in data else data.get("dataSources")
                if isinstance(probe, list):
                    return "another_rdm"
                entries = probe.values() if isinstance(probe, dict) else probe
                for entry in entries or []:
                    if isinstance(entry, dict) and (
                        "db_type" in entry or "transport_layers" in entry
                    ):
                        return "dbx"
                    break
                return "dbeaver"
        if isinstance(data, list):
            return "rdm"
        raise ValueError(f"unrecognised connection-export format in {file.name}")

    # Base64-wrapped JSON is Another Redis Desktop Manager's `.ano` layout.
    packed = re.sub(r"\s+", "", stripped)
    if packed and len(packed) % 4 == 0 and not re.search(r"[^A-Za-z0-9+/=]", packed):
        return "another_rdm"

    raise ValueError(f"unrecognised connection-export format in {file.name}")


def import_file(
    path: str | Path, fmt: str = "auto", passphrase: str = ""
) -> ConnectionImportResult:
    """Import connections from a file, sniffing the layout unless told which.

    ``fmt`` is one of :data:`FORMAT_KEYS` or ``"auto"``.  ``passphrase`` is only
    used by the ``dbx`` reader, whose encryption is published and reversible.
    """
    file = Path(path)
    key = detect_format(file) if fmt in ("", "auto", None) else get_format(fmt).key
    if key == "dbx":
        return parse_dbx(file, passphrase=passphrase)
    return _PARSERS[key](file)


# ── Saving ─────────────────────────────────────────────────────────────────


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


class ProfileStore(Protocol):
    """The two operations saving an import needs from a profile store.

    Declared as a protocol so the GUI can pass its own handle and a test can
    pass an in-memory fake without either side importing the concrete
    SQLite-backed ``local_db``.
    """

    def list_connections(self, group: str = "") -> list[ConnectionInfo]: ...

    def save_connection(self, info: ConnectionInfo) -> None: ...


def save_imported(
    connections: list[ImportedConnection],
    *,
    existing: list[ConnectionInfo] | None = None,
    dry_run: bool = False,
    store: ProfileStore | None = None,
) -> list[SaveOutcome]:
    """Persist imported connections, skipping duplicates.  Returns per-item outcomes.

    ``store`` defaults to the real profile database.  Callers that already hold
    a handle on one (the GUI keeps its own, and tests supply an in-memory fake)
    pass it explicitly so this function never reaches for global state that the
    caller does not control.
    """
    if store is None:
        from open_navicat.dal.local_config import local_db

        store = local_db  # type: ignore[assignment]

    if existing is None:
        existing = store.list_connections()
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
            store.save_connection(info)
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
