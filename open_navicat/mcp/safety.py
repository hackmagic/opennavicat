r"""Access policy for machine-driven query execution (MCP / AI agent).

Why this sits *in front of* the query engine instead of inside it: the same
:meth:`QueryEngine.execute` serves a human typing SQL in the GUI — who owns
the consequences — and an LLM that may have hallucinated a ``DELETE``.  Only
the machine path needs a gate, so the gate lives at the boundary the machine
path enters through.

Deliberate constraints:

* **No I/O, no SDK.**  This module parses text and returns decisions, so it is
  unit-testable without a database, a live session or the ``mcp`` package.
* **Fail closed.**  An unrecognised verb is high-risk, not "allowed because we
  did not think of it".  New engines cannot widen the policy by omission.
* **Static, therefore advisory.**  Classification is lexical over the
  de-commented statement.  It cannot see what a stored procedure body does.
  That is why ``CALL``/``EXEC`` are high-risk rather than write, and why the
  gate is an *additional* layer over least-privilege DB accounts, never a
  substitute for one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import sqlparse

from open_navicat.errors import PolicyDeniedError

# ---- tiers -----------------------------------------------------------------

TIER_READ = "read"
TIER_SAFE_WRITE = "safe-write"
TIER_FULL = "full"

#: Everything ``normalize_tier`` can return, in widening order.
TIERS: tuple[str, ...] = (TIER_READ, TIER_SAFE_WRITE, TIER_FULL)

#: Accepted spellings, including the ones humans type in config files.
_TIER_ALIASES: dict[str, str] = {
    "read": TIER_READ,
    "readonly": TIER_READ,
    "read-only": TIER_READ,
    "safe": TIER_SAFE_WRITE,
    "safe-write": TIER_SAFE_WRITE,
    "safewrite": TIER_SAFE_WRITE,
    "write": TIER_SAFE_WRITE,
    "full": TIER_FULL,
    "all": TIER_FULL,
    "unrestricted": TIER_FULL,
}


# ---- risk levels -----------------------------------------------------------

RISK_READ = "read"
RISK_WRITE = "write"
RISK_HIGH = "high-risk"

#: Escalation order; the highest risk in a batch rates the whole batch.
RISK_ORDER: dict[str, int] = {RISK_READ: 0, RISK_WRITE: 1, RISK_HIGH: 2}

#: Ceiling per tier.  ``full`` is the only tier that can reach ``high-risk``.
TIER_CEILING: dict[str, str] = {
    TIER_READ: RISK_READ,
    TIER_SAFE_WRITE: RISK_WRITE,
    TIER_FULL: RISK_HIGH,
}

# ---- verb tables -----------------------------------------------------------

_READ_VERBS = frozenset({"SELECT", "SHOW", "DESC", "DESCRIBE", "EXPLAIN", "VALUES", "WITH"})

#: Data-changing but reversible-in-principle statements.  ``UPDATE``/``DELETE``
#: are escalated to high-risk when they carry no ``WHERE``.
_WRITE_VERBS = frozenset({"INSERT", "REPLACE", "UPDATE", "DELETE", "CREATE", "MERGE", "SET"})

#: Anything that destroys data, grants privileges or whose effect cannot be
#: read off the statement text.
_HIGH_VERBS = frozenset(
    {
        "DROP",
        "TRUNCATE",
        "ALTER",
        "RENAME",
        "GRANT",
        "REVOKE",
        "CALL",
        "EXEC",
        "EXECUTE",
        "DO",
        "LOAD",
        "COPY",
        "VACUUM",
        "ANALYZE",  # rewrites planner statistics
        "REINDEX",
        "CLUSTER",
        "LOCK",
        "UNLOCK",
        "KILL",
    }
)

# ---- Redis command tables --------------------------------------------------

#: Read-only Redis commands.  An allowlist rather than a write-verb table:
#: anything not listed is assumed to change state, so a command Redis adds
#: later cannot slip through as "read".  ``KEYS`` is excluded on purpose — it
#: changes nothing, but its O(N) scan can freeze a production instance.
_CMD_READ = frozenset(
    {
        "GET",
        "MGET",
        "GETRANGE",
        "STRLEN",
        "GETBIT",
        "BITCOUNT",
        "BITPOS",
        "TYPE",
        "TTL",
        "PTTL",
        "EXISTS",
        "EXPIRETIME",
        "DUMP",
        "OBJECT",
        "SCAN",
        "HSCAN",
        "SSCAN",
        "ZSCAN",
        "RANDOMKEY",
        "DBSIZE",
        "INFO",
        "PING",
        "ECHO",
        "TIME",
        "MEMORY",
        "LATENCY",
        "SLOWLOG",
        "COMMAND",
        "HGET",
        "HMGET",
        "HGETALL",
        "HKEYS",
        "HVALS",
        "HLEN",
        "HEXISTS",
        "HSTRLEN",
        "HRANDFIELD",
        "LLEN",
        "LRANGE",
        "LINDEX",
        "LPOS",
        "SCARD",
        "SMEMBERS",
        "SISMEMBER",
        "SRANDMEMBER",
        "ZCARD",
        "ZCOUNT",
        "ZRANGE",
        "ZREVRANGE",
        "ZRANGEBYSCORE",
        "ZRANGEBYLEX",
        "ZSCORE",
        "ZRANK",
        "ZREVRANK",
        "GEODIST",
        "GEOPOS",
        "GEORADIUS",
        "GEORADIUSBYMEMBER",
        "GEOSEARCH",
        "XLEN",
        "XRANGE",
        "XREVRANGE",
        "XREAD",
        "XINFO",
        "XPENDING",
    }
)

#: Commands that wipe a keyspace, run arbitrary code, or reconfigure the server.
_CMD_HIGH = frozenset(
    {
        "FLUSHALL",
        "FLUSHDB",
        "KEYS",
        "CONFIG",
        "DEBUG",
        "SHUTDOWN",
        "SAVE",
        "BGSAVE",
        "BGREWRITEAOF",
        "MIGRATE",
        "RESTORE",
        "SCRIPT",
        "EVAL",
        "EVALSHA",
        "FCALL",
        "FCALL_RO",
        "CLIENT",
        "CLUSTER",
        "SWAPDB",
        "RENAME",
    }
)

#: Statements that reach outside the database engine.  Matching these on the
#: *body* (not just the leading verb) catches the classic "innocent SELECT"
#: that reads a file, calls the OS or opens a network link.
_ESCAPE_HATCH = re.compile(
    r"\b(load_file|pg_read_file|pg_read_binary_file|pg_ls_dir|lo_import|lo_export|"
    r"dblink|xp_cmdshell|sp_executesql|utl_http|utl_file|dbms_lob|group_concat\.file)\b",
    re.IGNORECASE,
)

_OUTFILE = re.compile(r"\binto\s+(outfile|dumpfile)\b", re.IGNORECASE)
_GLOBAL_MUTATION = re.compile(r"\b(set\s+global|alter\s+system)\b", re.IGNORECASE)
_WHERE = re.compile(r"\bwhere\b", re.IGNORECASE)
_DML_IN_CTE = re.compile(r"\b(insert|update|delete|merge)\b", re.IGNORECASE)
_EXECUTABLE_DDL = re.compile(
    r"create\s+(?:or\s+replace\s+)?(?:function|procedure|trigger|rule|event)\b", re.IGNORECASE
)
_ANALYZE_WORD = re.compile(r"\banaly[sz]e\b", re.IGNORECASE)
_EXPLAIN_PREFIX = re.compile(r"^explain\b(?:\s*\([^)]*\))?(?:\s+analy[sz]e\b)?\s*", re.IGNORECASE)
_INSERT_INTO = re.compile(r"\b(insert|replace)\s+into\b", re.IGNORECASE)
_SELECT_INTO = re.compile(r"\bselect\b[\s\S]*?\binto\b\s+[`\"\[\w]", re.IGNORECASE)
# The target of a write; quote chars are stripped afterwards, so a permissive
# run of non-delimiter characters is enough here.
_TABLE = re.compile(r"\b(?:update|from|into)\s+([^\s,;()]+)", re.IGNORECASE)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LEADING_PAREN = re.compile(r"^[\s(]*")
#: String literals only — MySQL/ANSI single quotes with both escape styles,
#: backslash escapes, and PostgreSQL dollar quoting.  Identifiers are left
#: alone so table names stay readable.
_LITERAL = re.compile(
    r"'(?:[^'\\]|\\.|'')*'|\$([A-Za-z_0-9]*)\$.*?\$\1\$", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True)
class Statement:
    """One classified SQL statement or key command."""

    sql: str
    verb: str
    risk: str
    #: Why this statement is not merely ``read`` — shown to the agent verbatim,
    #: so it has to be a sentence a human would recognise as the reason.
    reasons: tuple[str, ...] = ()
    table: str = ""
    #: True when an UPDATE/DELETE is row-scoped, False when it is unbounded,
    #: None when the concept does not apply (SELECT, INSERT, DDL...).
    qualified: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verb": self.verb,
            "risk": self.risk,
            "reasons": list(self.reasons),
            "table": self.table,
            "qualified": self.qualified,
        }


@dataclass(frozen=True)
class Analysis:
    """Classification of a whole request (possibly several statements)."""

    risk: str
    statements: tuple[Statement, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def is_read_only(self) -> bool:
        return self.risk == RISK_READ

    @property
    def tables(self) -> tuple[str, ...]:
        seen: list[str] = []
        for stmt in self.statements:
            if stmt.table and stmt.table not in seen:
                seen.append(stmt.table)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "reasons": list(self.reasons),
            "statements": [s.to_dict() for s in self.statements],
        }


def normalize_tier(value: str | None, default: str = TIER_READ) -> str:
    """Return the canonical tier name for ``value``.

    Empty/None falls back to ``default``; an unknown spelling raises
    :class:`PolicyDeniedError` rather than silently degrading to ``full`` —
    a typo in a config file must not widen access.
    """
    if value is None or not str(value).strip():
        return default
    key = re.sub(r"[\s_]+", "-", str(value).strip().lower())
    tier = _TIER_ALIASES.get(key)
    if tier is None:
        raise PolicyDeniedError(
            f"unknown access tier {value!r}; expected one of "
            + ", ".join(f"'{t}'" for t in (TIER_READ, TIER_SAFE_WRITE, TIER_FULL)),
            recoverable=True,
        )
    return tier


def clamp_tier(requested: str | None, ceiling: str | None) -> str:
    """The narrower of two tiers.

    Used for the operator's own limit, which is a ceiling rather than a default:
    a client may ask for a wider tier, but asking is not the same as being
    allowed.  An empty ceiling means no limit was configured.
    """
    want = normalize_tier(requested)
    if ceiling is None or not str(ceiling).strip():
        return want
    limit = normalize_tier(ceiling)
    return want if TIERS.index(want) <= TIERS.index(limit) else limit


def _strip_comments(sql: str) -> str:
    """Remove ``--`` / ``#`` / ``/* */`` comments so they cannot hide keywords.

    sqlparse is used rather than a hand-rolled regex because a ``/*`` inside a
    string literal must *not* be treated as a comment start.
    """
    return sqlparse.format(sql, strip_comments=True, encoding="utf-8")


def _leading_verb(body: str) -> str:
    """First word of a statement, tolerating ``(SELECT ...)`` and whitespace."""
    match = _IDENT.match(_LEADING_PAREN.sub("", body))
    return match.group(0).upper() if match else ""


def _mask_literals(body: str) -> str:
    """Blank out string literals, keeping every other character's offset.

    Keyword classification runs on this copy: ``UPDATE t SET note = 'where'``
    contains no predicate, and reading the literal as one would rate an
    unbounded write as row-scoped.  Offsets are preserved so a predicate found
    here can still be sliced out of the original statement.
    """
    return _LITERAL.sub(lambda m: " " * len(m.group(0)), body)


def _escalate(risk: str, floor: str) -> str:
    """Never downgrade: an outer read wrapper does not make an inner write safe."""
    return risk if RISK_ORDER[risk] >= RISK_ORDER[floor] else floor


def _table_of(body: str) -> str:
    match = _TABLE.search(body)
    if not match:
        return ""
    # Delimiters are removed rather than just trimmed at the ends, so
    # SQL Server's `[dbo].[users]` normalises to the usable `dbo.users`.
    return re.sub(r"[`\[\]\"]", "", match.group(1))


def _worst(risks: list[str]) -> str:
    return max(risks, key=lambda risk: RISK_ORDER[risk]) if risks else RISK_READ


def classify_statement(sql: str) -> Statement:
    """Rate a single statement as read / write / high-risk."""
    body = _strip_comments(sql).strip().rstrip(";").strip()
    # Keywords are matched against the literal-masked copy (same offsets); the
    # statement text itself is kept verbatim so a preview can be sliced out.
    probe = _mask_literals(body)
    verb = _leading_verb(probe)
    if not verb:
        return Statement(sql=body, verb="", risk=RISK_HIGH, reasons=("no statement to classify",))

    reasons: list[str] = []
    qualified: bool | None = None

    if verb in _READ_VERBS:
        risk = RISK_READ
    elif verb in _WRITE_VERBS:
        risk = RISK_WRITE
        if verb in ("UPDATE", "DELETE"):
            qualified = bool(_WHERE.search(probe))
            if not qualified:
                # A write with no predicate is the classic way an agent empties
                # a table, and `safe-write` is a promise that it cannot.
                risk = RISK_HIGH
                reasons.append(f"{verb} without a WHERE clause touches every row")
        if verb == "CREATE" and _EXECUTABLE_DDL.match(probe):
            risk = RISK_HIGH
            reasons.append("statement defines executable code whose body is not visible here")
    elif verb in _HIGH_VERBS:
        risk = RISK_HIGH
        if verb in ("CALL", "EXEC", "EXECUTE"):
            reasons.append("the body of a stored routine is not visible to static analysis")
    else:
        # Fail closed: an engine we do not know must not widen the policy just
        # because nobody added its verb to a table.
        risk = RISK_HIGH
        reasons.append(f"`{verb}` is not a recognised read or write verb; treated as high-risk")

    # Form-level checks apply whatever the leading verb was.  `INSERT INTO t`
    # also contains an `INTO`, so it is masked before the SELECT ... INTO test.
    into_probe = _INSERT_INTO.sub(lambda m: m.group(1), probe)
    if _SELECT_INTO.search(into_probe):
        risk = _escalate(risk, RISK_WRITE)
        reasons.append("`SELECT ... INTO` creates a table")
    if verb == "WITH" and _DML_IN_CTE.search(probe):
        risk = _escalate(risk, RISK_WRITE)
        reasons.append("common table expression ends in a data-modifying statement")
    if verb == "EXPLAIN" and _ANALYZE_WORD.search(probe):
        inner = _EXPLAIN_PREFIX.sub("", body, count=1)
        if inner and _leading_verb(inner) != "EXPLAIN":
            # EXPLAIN ANALYZE really runs the statement it explains, so its
            # risk is the inner statement's risk — not "read" because the first
            # keyword happens to be EXPLAIN.
            inner_risk = classify_statement(inner).risk
            if RISK_ORDER[inner_risk] > RISK_ORDER[risk]:
                reasons.append("EXPLAIN ANALYZE executes the statement it explains")
                risk = inner_risk
    if _ESCAPE_HATCH.search(probe):
        risk = _escalate(risk, RISK_HIGH)
        reasons.append("statement reaches outside the database (files, OS or network)")
    if _OUTFILE.search(probe):
        risk = _escalate(risk, RISK_HIGH)
        reasons.append("statement writes a file on the server")
    if _GLOBAL_MUTATION.search(probe):
        risk = _escalate(risk, RISK_HIGH)
        reasons.append("statement changes server-wide configuration")

    return Statement(
        sql=body,
        verb=verb,
        risk=risk,
        reasons=tuple(reasons),
        table=_table_of(probe),
        qualified=qualified,
    )


def analyze(sql: str) -> Analysis:
    """Classify a request that may contain several statements.

    A batch is rated by its worst member; a batch that contains any write is
    rated high-risk outright, because most drivers run the statements
    sequentially with no rollback point between them.
    """
    body = _strip_comments(sql)
    chunks = [c.strip() for c in sqlparse.split(body) if c and c.strip()]
    if not chunks:
        stmt = classify_statement(sql)
        return Analysis(risk=stmt.risk, statements=(stmt,), reasons=stmt.reasons)

    statements = tuple(classify_statement(chunk) for chunk in chunks)
    reasons = list(dict.fromkeys(r for s in statements for r in s.reasons))
    risk = _worst([s.risk for s in statements])
    if len(statements) > 1:
        reasons.insert(
            0,
            f"batch of {len(statements)} statements executes sequentially, with no rollback "
            "point between them",
        )
        if risk != RISK_READ:
            # A write hidden behind a read is the reason multi-statement input
            # is not allowed to inherit the first statement's rating.
            risk = RISK_HIGH
    return Analysis(risk=risk, statements=statements, reasons=tuple(reasons))


def analyze_command(command: str) -> Analysis:
    """Classify a Redis command line.

    Deliberately not routed through :func:`analyze` — Redis commands are not
    SQL, and feeding ``SET key "a;b"`` to a statement splitter would invent a
    second statement out of a value.  Anything that is not on the read
    allowlist is treated as a write, so an unknown command costs a confirmation
    rather than silently running under tier ``read``.
    """
    text = " ".join(command.strip().split())
    if not text:
        return Analysis(risk=RISK_HIGH, reasons=("empty command",))

    verb = text.split(" ", 1)[0].upper()
    reasons: list[str] = []
    if verb in _CMD_HIGH:
        risk = RISK_HIGH
        reasons.append(f"{verb} is administrative or affects more than the named keys")
    elif verb == "SORT":
        if re.search(r"\bstore\b", text, re.IGNORECASE):
            risk = RISK_WRITE
            reasons.append("SORT ... STORE writes a key")
        else:
            risk = RISK_READ
    elif verb in _CMD_READ:
        risk = RISK_READ
    else:
        risk = RISK_WRITE
        reasons.append(f"{verb} is not on the read-only command list, so it counts as a write")

    statement = Statement(sql=text, verb=verb, risk=risk, reasons=tuple(reasons))
    return Analysis(risk=risk, statements=(statement,), reasons=tuple(reasons))


def dry_run_preview(analysis: Analysis) -> str | None:
    """Build a SELECT that reports what a row-scoped write *would* touch.

    Only UPDATE/DELETE with a WHERE clause can be previewed honestly — for
    those, ``COUNT(*)`` under the same predicate is the same row set the write
    targets.  Everything else returns None so the caller cannot mistake an
    empty preview for a verified plan.
    """
    if len(analysis.statements) != 1:
        return None
    stmt = analysis.statements[0]
    if stmt.verb not in ("UPDATE", "DELETE") or not stmt.qualified or not stmt.table:
        return None
    # Search the masked copy for the offset, slice the original: literals keep
    # their length, so the two are aligned and `WHERE` inside a value cannot
    # truncate the predicate.
    match = _WHERE.search(_mask_literals(stmt.sql))
    if not match:
        return None
    predicate = stmt.sql[match.end() :].strip().rstrip(";").strip()
    if not predicate:
        return None
    return f"SELECT COUNT(*) AS matching_rows FROM {stmt.table} WHERE {predicate}"


@dataclass(frozen=True)
class Decision:
    """The gate's answer to "may I run this now?".

    ``allowed`` is only True when the tier reaches this risk *and* the caller
    has satisfied the confirmation requirement — tier and confirmation are
    independent axes, and an agent that passes one still has to pass the other.
    """

    allowed: bool
    tier: str
    risk: str
    reasons: tuple[str, ...] = ()
    dry_run: bool = False
    needs_confirm: bool = False
    preview_sql: str | None = None
    error: PolicyDeniedError | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "allowed": self.allowed,
            "tier": self.tier,
            "risk": self.risk,
            "reasons": list(self.reasons),
            "dryRun": self.dry_run,
        }
        if self.needs_confirm:
            payload["needsConfirm"] = True
        if self.preview_sql:
            payload["previewSql"] = self.preview_sql
        if self.error is not None:
            payload["error"] = self.error.to_dict()
        return payload


def _refusal(message: str, reasons: tuple[str, ...]) -> PolicyDeniedError:
    """Compose the refusal an agent receives instead of a stack trace.

    The reasons are appended because the caller is usually an LLM that will
    re-plan from this text; a bare "denied" makes it guess.  ASCII only, since
    these strings are printed on Windows consoles that cannot encode more.
    """
    detail = f"{message}: " + "; ".join(reasons) if reasons else message
    return PolicyDeniedError(f"{detail}.", recoverable=True)


def decide(
    analysis: Analysis,
    *,
    tier: str = TIER_READ,
    dry_run: bool = False,
    confirm: bool = False,
) -> Decision:
    """Apply the tier and confirmation rules to an already-classified request.

    Split from :func:`check` because the right classifier depends on the engine:
    Redis commands and SQL are rated differently, and the caller is the one that
    knows which it has.
    """
    resolved = normalize_tier(tier)

    if analysis.risk == RISK_READ:
        return Decision(allowed=True, tier=resolved, risk=analysis.risk, reasons=analysis.reasons)

    if dry_run:
        # Nothing changes on a dry run, so there is nothing for the tier to gate:
        # the caller gets the analysis plus, for a row-scoped write, a COUNT
        # query -- which is a read every tier already permits.
        return Decision(
            allowed=True,
            tier=resolved,
            risk=analysis.risk,
            reasons=analysis.reasons,
            dry_run=True,
            preview_sql=dry_run_preview(analysis),
        )

    ceiling = TIER_CEILING[resolved]
    if RISK_ORDER[analysis.risk] > RISK_ORDER[ceiling]:
        allowed_risks = "/".join(
            name for name, rank in RISK_ORDER.items() if rank <= RISK_ORDER[ceiling]
        )
        return Decision(
            allowed=False,
            tier=resolved,
            risk=analysis.risk,
            reasons=analysis.reasons,
            error=_refusal(
                f"the '{resolved}' access tier only permits {allowed_risks} operations, "
                f"this is {analysis.risk}",
                analysis.reasons,
            ),
        )

    if not confirm:
        return Decision(
            allowed=False,
            tier=resolved,
            risk=analysis.risk,
            reasons=analysis.reasons,
            needs_confirm=True,
            error=_refusal(
                f"this {analysis.risk} operation was not confirmed: re-run with dry_run=true to "
                "see what it affects, or confirm=true to execute it",
                analysis.reasons,
            ),
        )

    return Decision(
        allowed=True,
        tier=resolved,
        risk=analysis.risk,
        reasons=analysis.reasons,
    )


def check(
    sql: str,
    *,
    tier: str = TIER_READ,
    dry_run: bool = False,
    confirm: bool = False,
    command: bool = False,
) -> Decision:
    """Classify ``sql`` (or a Redis ``command``) and gate it under ``tier``.

    Rules, in order:

    1. read-only work always runs — every tier allows it;
    2. ``dry_run=True`` never executes the statement, so it always runs, at any
       tier;
    3. a real change needs ``confirm=True``, including at tier ``full`` —
       ``full`` widens *what* may run, it never removes the requirement to say so;
    4. and the tier must reach the statement's risk level.
    """
    analysis = analyze_command(sql) if command else analyze(sql)
    return decide(analysis, tier=tier, dry_run=dry_run, confirm=confirm)


__all__ = [
    "Analysis",
    "Decision",
    "RISK_HIGH",
    "RISK_ORDER",
    "RISK_READ",
    "RISK_WRITE",
    "Statement",
    "TIER_CEILING",
    "TIER_FULL",
    "TIER_READ",
    "TIER_SAFE_WRITE",
    "TIERS",
    "analyze",
    "analyze_command",
    "check",
    "clamp_tier",
    "classify_statement",
    "dry_run_preview",
    "normalize_tier",
]
