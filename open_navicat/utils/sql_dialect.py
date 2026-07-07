"""SQL dialect translation using sqlglot."""

from __future__ import annotations

import logging

import sqlglot
import sqlglot.optimizer

logger = logging.getLogger("opennavicat.sql_dialect")

DIALECTS = {"mysql": "mysql", "postgresql": "postgres", "postgres": "postgres"}


def translate_sql(sql: str, source: str, target: str) -> str:
    """Translate SQL between dialects (mysql ↔ postgresql).

    Args:
        sql: SQL statement to translate.
        source: Source dialect name ('mysql' or 'postgresql').
        target: Target dialect name ('mysql' or 'postgresql').

    Returns:
        Translated SQL string, or original on failure.
    """
    src = DIALECTS.get(source.lower(), source.lower())
    dst = DIALECTS.get(target.lower(), target.lower())
    try:
        return sqlglot.transpile(sql, read=src, write=dst)[0]
    except Exception as e:
        logger.warning("SQL dialect translation failed: %s", e)
        return sql


def optimize_sql(sql: str, dialect: str = "mysql") -> str:
    """Optimize SQL using sqlglot's built-in optimizer.

    Applies: predicate pushdown, qualifier removal, etc.
    """
    d = DIALECTS.get(dialect.lower(), dialect.lower())
    try:
        tree = sqlglot.parse_one(sql, read=d)
        optimized = sqlglot.optimizer.optimize(tree, dialect=d)
        return optimized.sql(dialect=d)
    except Exception as e:
        logger.warning("SQL optimization failed: %s", e)
        return sql
