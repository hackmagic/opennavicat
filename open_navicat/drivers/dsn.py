"""Connection-string (DSN) parsing and formatting.

Accepted forms::

    mysql://user:pass@host:3306/dbname?charset=utf8mb4
    postgresql://user@host/db?ssl=require&connect_timeout=5
    sqlserver://sa:pass@host:1433/db
    redis://:pass@host:6379/0
    mongodb://user:pass@host:27017/db
    sqlite:///absolute/path.db          # three slashes = absolute path
    sqlite://relative/path.db           # two slashes  = relative path
    duckdb:///:memory:                  # in-memory duckdb
    duckdb:///data/warehouse.duckdb

Percent-encoded credentials are decoded on parse and re-encoded on format, so
``mysql://user:p%40ss@host/db`` yields the password ``p@ss``.

This module deliberately does **not** know about ``ConnectionInfo`` at import
time: ``models`` is the bottom layer and must not depend on ``drivers``.  The
dependency is imported lazily inside the two conversion helpers instead.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote, urlsplit

from open_navicat.drivers.registry import file_engines, get_spec, normalize_engine
from open_navicat.errors import ConfigError, EngineNotSupportedError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from open_navicat.models.connection import ConnectionInfo

_log = logging.getLogger("opennavicat.dsn")

#: `C:` style prefix, used to detect Windows absolute paths inside a URL path.
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
#: Values that mean "true" in a DSN query string.
_TRUTHY = frozenset({"1", "true", "yes", "on", "require", "required", "enable", "enabled"})

#: Query-string option names we know how to map onto ``ConnectionInfo``.
_OPT_CHARSET = ("charset", "encoding")
_OPT_SSL = ("ssl", "sslmode", "tls")
_OPT_POOL_MIN = ("pool_min", "minsize", "min_size")
_OPT_POOL_MAX = ("pool_max", "maxsize", "max_size")
_OPT_TIMEOUT = ("connect_timeout", "timeout", "connection_timeout")

#: Engines that are backed by a single file rather than host+port.
#: Derived from the registry so adding one is still a one-row change there.
FILE_ENGINES = frozenset(file_engines())


@dataclass(frozen=True)
class Dsn:
    """A parsed connection string."""

    engine: str
    host: str = ""
    port: int = 0
    user: str = ""
    password: str = ""
    database: str = ""
    options: dict[str, str] = field(default_factory=dict)

    @property
    def is_file_based(self) -> bool:
        return self.engine in FILE_ENGINES

    def to_dsn(self, *, include_password: bool = False) -> str:
        """Render back to a URL.  Password is omitted unless asked for."""
        userinfo = ""
        if not self.is_file_based:
            # File engines have no credentials, so a ConnectionInfo default of
            # user="root" must not leak into the URL as "sqlite://root@/path".
            if self.user:
                userinfo = quote(self.user, safe="")
                if include_password and self.password:
                    userinfo += ":" + quote(self.password, safe="")
                userinfo += "@"
            elif include_password and self.password:
                userinfo += ":" + quote(self.password, safe="") + "@"

        if self.is_file_based:
            # File engines carry the path in `database`.  Absolute paths already
            # start with "/" (giving the three-slash form); relative paths and
            # Windows drives need one added.  Windows drives stay in the
            # three-slash form because the parser strips that leading slash back.
            path = self.database or ""
            if path == ":memory:":
                url_path = "/:memory:"
            elif path.startswith("/"):
                url_path = path
            elif _WINDOWS_DRIVE.match(path):
                url_path = "/" + path
            else:
                # Genuinely relative: no netloc, so "scheme:path" round-trips.
                url = f"{self.engine}:{path}"
                if self.options:
                    query = "&".join(
                        f"{k}={quote(v, safe='')}" for k, v in sorted(self.options.items())
                    )
                    url = f"{url}?{query}"
                return url
            url = f"{self.engine}://{userinfo}{url_path}"
        else:
            netloc = self.host
            if self.port:
                netloc = f"{netloc}:{self.port}"
            db = f"/{self.database}" if self.database else ""
            url = f"{self.engine}://{userinfo}{netloc}{db}"

        if self.options:
            query = "&".join(f"{k}={quote(v, safe='')}" for k, v in sorted(self.options.items()))
            url = f"{url}?{query}"
        return url

    def redacted(self) -> str:
        """URL safe to log or show in a UI."""
        return self.to_dsn(include_password=False)


def _split_userinfo(netloc: str) -> tuple[str, str, str]:
    """``user:pass@host:port`` -> ``(user, password, host:port)``."""
    if "@" in netloc:
        userinfo, _, hostport = netloc.rpartition("@")
    else:
        userinfo, hostport = "", netloc
    if not userinfo:
        return "", "", hostport
    user, sep, password = userinfo.partition(":")
    return unquote(user), (unquote(password) if sep else ""), hostport


def _split_hostport(hostport: str) -> tuple[str, int | None]:
    """``host`` / ``host:port`` / ``[v6::addr]:port`` -> ``(host, port)``."""
    if not hostport:
        return "", None
    if hostport.startswith("["):  # bracketed IPv6 literal
        host, _, rest = hostport[1:].partition("]")
        if rest.startswith(":"):
            digits = rest[1:]
            if not digits.isdigit():
                raise ConfigError(f"invalid port in DSN host '{hostport}'")
            return host, int(digits)
        return host, None
    host, sep, digits = hostport.rpartition(":")
    if not sep:
        return hostport, None
    if not digits.isdigit():
        raise ConfigError(f"invalid port '{digits}' in DSN host '{hostport}'; expected a number")
    return host, int(digits)


def _file_path_from_url(netloc: str, path: str) -> str:
    """Resolve the file path for sqlite/duckdb DSNs.

    ``netloc + path`` keeps the three-slash and two-slash forms distinct:

    * ``sqlite:///abs.db``  -> netloc ``""`` + path ``"/abs.db"`` -> ``/abs.db``
    * ``sqlite://rel.db``   -> netloc ``"rel.db"`` + path ``""``     -> ``rel.db``
    * ``duckdb:///:memory:``-> ``/:memory:``                          -> ``:memory:``
    """
    raw = f"{netloc}{path}"
    if raw.startswith("//"):
        # `sqlite:////abs/db` (four slashes) is the other common spelling for an
        # absolute path; collapse so both forms land on "/abs/db".
        raw = raw[1:]
    if raw.lstrip("/") == ":memory:":  # in-memory shorthand
        return ":memory:"
    if raw.startswith("/") and _WINDOWS_DRIVE.match(raw[1:]):
        return raw[1:]  # /C:/data/x.db -> C:/data/x.db
    return raw


def parse_dsn(url: str) -> Dsn:
    """Parse ``url`` into a :class:`Dsn`.

    Raises :class:`EngineNotSupportedError` for an unknown scheme and
    :class:`ConfigError` for a structurally invalid URL.
    """
    text = (url or "").strip()
    if not text:
        raise ConfigError("empty connection string")
    if "://" not in text:
        # `sqlite:relative.db` / `duckdb::memory:` carry a path with no netloc.
        scheme, sep, rest = text.partition(":")
        if sep:
            try:
                spec = get_spec(scheme)
            except EngineNotSupportedError:
                raise
            engine = normalize_engine(scheme)
            if spec.default_port == 0 or engine in FILE_ENGINES:
                return Dsn(engine=engine, database=_file_path_from_url("", rest))
        raise ConfigError(
            f"connection string must look like 'scheme://[user[:pass]@]host[:port][/db]'; got {text!r}"
        )

    parts = urlsplit(text)
    try:
        spec = get_spec(parts.scheme)
    except EngineNotSupportedError:
        raise
    except Exception as exc:  # noqa: BLE001 - defensive
        raise ConfigError(f"could not resolve engine for {text!r}: {exc}") from exc

    engine = normalize_engine(parts.scheme)
    user, password, hostport = _split_userinfo(parts.netloc)
    options = _parse_query(parts.query)

    if spec.default_port == 0 or engine in FILE_ENGINES:
        return Dsn(
            engine=engine,
            user=user,
            password=password,
            database=_file_path_from_url(parts.netloc, parts.path),
            options=options,
        )

    host, port = _split_hostport(hostport)
    database = parts.path.lstrip("/")
    return Dsn(
        engine=engine,
        host=host or "127.0.0.1",
        port=port or spec.default_port,
        user=user,
        password=password,
        database=database,
        options=options,
    )


def _parse_query(query: str) -> dict[str, str]:
    """Parse a DSN query string into a plain dict, last value wins."""
    out: dict[str, str] = {}
    if not query:
        return out
    for chunk in query.split("&"):
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        key = unquote(key).strip().lower()
        if key:
            out[key] = unquote(value)
    return out


def _first(options: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in options:
            return options[name]
    return None


def _as_int(value: str, option: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"option '{option}' must be an integer, got {value!r}") from exc


def dsn_to_connection(url: str, *, name: str = "", **overrides: Any) -> ConnectionInfo:
    """Build a :class:`ConnectionInfo` from a connection string.

    Recognised query options are applied; anything else is preserved on the
    :class:`Dsn` but cannot live on ``ConnectionInfo``, so it is logged at debug
    level rather than silently dropped.
    """
    from open_navicat.models.connection import ConnectionInfo

    parsed = parse_dsn(url)
    spec = get_spec(parsed.engine)

    fields: dict[str, Any] = {"engine": parsed.engine, "name": name}
    if parsed.is_file_based:
        # Clear the defaults: SQLiteConnector treats a non-empty host as the
        # file path, so leaving "127.0.0.1" here would open a bogus database.
        fields["host"] = ""
        fields["port"] = 0
        fields["database"] = parsed.database
    else:
        fields["host"] = parsed.host
        fields["port"] = parsed.port or spec.default_port
        fields["database"] = parsed.database
    fields["user"] = parsed.user
    fields["password"] = parsed.password

    opts = parsed.options
    charset = _first(opts, _OPT_CHARSET)
    if charset:
        fields["charset"] = charset
    ssl_value = _first(opts, _OPT_SSL)
    if ssl_value is not None:
        fields["use_ssl"] = ssl_value.strip().lower() in _TRUTHY
    pool_min = _first(opts, _OPT_POOL_MIN)
    if pool_min is not None:
        fields["pool_min"] = _as_int(pool_min, "pool_min")
    pool_max = _first(opts, _OPT_POOL_MAX)
    if pool_max is not None:
        fields["pool_max"] = _as_int(pool_max, "pool_max")
    timeout = _first(opts, _OPT_TIMEOUT)
    if timeout is not None:
        fields["connect_timeout"] = _as_int(timeout, "connect_timeout")

    known = set(_OPT_CHARSET + _OPT_SSL + _OPT_POOL_MIN + _OPT_POOL_MAX + _OPT_TIMEOUT)
    unknown = {k: v for k, v in opts.items() if k not in known}
    if unknown:
        _log.debug("DSN options not representable on ConnectionInfo: %s", sorted(unknown))

    fields.update(overrides)
    return ConnectionInfo(**fields)


def info_to_dsn(info: ConnectionInfo, *, include_password: bool = False) -> str:
    """Render a :class:`ConnectionInfo` as a connection string."""
    parsed = Dsn(
        engine=normalize_engine(info.engine),
        host=info.host,
        port=info.port,
        user=info.user,
        password=info.password,
        database=info.database,
    )
    if parsed.engine in FILE_ENGINES:
        # Also accept the legacy layout where SQLite kept the path in `host`.
        parsed = Dsn(
            engine=parsed.engine,
            database=info.database or (info.host if parsed.engine == "sqlite" else ""),
            user=info.user,
            password=info.password,
        )
    return parsed.to_dsn(include_password=include_password)


__all__ = [
    "Dsn",
    "FILE_ENGINES",
    "dsn_to_connection",
    "info_to_dsn",
    "parse_dsn",
]
