"""SQL formatting and beautification utilities."""

from __future__ import annotations

import sqlparse
from sqlparse import tokens as T


def beautify(sql: str, keyword_case: str = "upper") -> str:
    """Format SQL with consistent indentation and keyword casing."""
    return sqlparse.format(
        sql,
        reindent=True,
        reindent_aligned=True,
        keyword_case=keyword_case,
        strip_comments=False,
    )


def minify(sql: str) -> str:
    """Remove unnecessary whitespace, returning compact SQL."""
    return sqlparse.format(
        sql,
        strip_whitespace=True,
        keyword_case="upper",
        compact=True,
    )


def extract_table_names(sql: str) -> list[str]:
    """Parse SQL and extract referenced table names."""
    parsed = sqlparse.parse(sql)
    tables: list[str] = []
    if not parsed:
        return tables
    stmt = parsed[0]
    in_from = False
    for token in stmt.tokens:
        if token.ttype is T.Keyword and token.value.upper() in ("FROM", "JOIN", "INTO", "TABLE", "UPDATE"):
            in_from = True
            continue
        if in_from:
            if isinstance(token, sqlparse.sql.Identifier):
                tables.append(token.get_real_name() or str(token))
                in_from = False
            elif token.ttype is T.Keyword:
                in_from = False
            elif token.ttype is T.Punctuation:
                continue
    return tables


def split_statements(sql: str) -> list[str]:
    """Split a multi-statement SQL script into individual statements."""
    return [
        s.strip()
        for s in sqlparse.split(sql)
        if s.strip()
    ]


def is_select(sql: str) -> bool:
    """Check if a SQL statement is a SELECT query."""
    parsed = sqlparse.parse(sql)
    if not parsed:
        return False
    stmt = parsed[0]
    return stmt.get_type() == "SELECT"


def is_ddl(sql: str) -> bool:
    """Check if a SQL statement is DDL (CREATE/ALTER/DROP)."""
    parsed = sqlparse.parse(sql)
    if not parsed:
        return False
    return parsed[0].get_type() in ("CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME")


def is_dml(sql: str) -> bool:
    """Check if a SQL statement is DML (INSERT/UPDATE/DELETE)."""
    parsed = sqlparse.parse(sql)
    if not parsed:
        return False
    return parsed[0].get_type() in ("INSERT", "UPDATE", "DELETE", "REPLACE")
