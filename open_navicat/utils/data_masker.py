"""Data masking utility — replaces sensitive data before sending to LLM."""

from __future__ import annotations

import re
from typing import Any


def mask_row(row: list[Any], columns: list[str]) -> list[Any]:
    """Mask sensitive values in a single row based on column name heuristics."""
    masked: list[Any] = []
    for col, val in zip(columns, row):
        if val is None:
            masked.append(None)
            continue
        col_lower = col.lower()
        if isinstance(val, str):
            val = _mask_string(val, col_lower)
        elif isinstance(val, int):
            val = _mask_int(val, col_lower)
        masked.append(val)
    return masked


def _mask_string(val: str, col: str) -> str:
    if "email" in col or "mail" in col:
        return re.sub(r"[^@\s]+@[^@\s]+\.[^@\s]+", "redacted@example.com", val)
    if "phone" in col or "mobile" in col or "tel" in col or "fax" in col:
        return re.sub(r"\d", "x", val)
    if "name" in col or "username" in col or "login" in col:
        if len(val) <= 2:
            return val[0] + "*"
        return val[0] + "*" * (len(val) - 2) + val[-1]
    if "password" in col or "secret" in col or "token" in col or "key" in col:
        return "****"
    if "address" in col or "street" in col or "city" in col:
        return "[redacted]"
    return val


def _mask_int(val: int, col: str) -> int | str:
    if col in ("id", "user_id", "customer_id", "account_id", "employee_id"):
        return val
    if "phone" in col or "mobile" in col or "tel" in col or "fax" in col:
        return int("".join("x" for _ in str(val)))
    if "credit" in col or "card" in col or "cvv" in col or "cvc" in col:
        return int(str(val)[:1] + "x" * (len(str(val)) - 1))
    if "ssn" in col or "social" in col or "tax" in col:
        return int(str(val)[0] + "x" * (len(str(val)) - 1))
    return val
