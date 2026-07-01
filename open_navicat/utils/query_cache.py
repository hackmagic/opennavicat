"""Query result cache — in-memory LRU with TTL."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class QueryCache:
    """Simple LRU cache for query results with TTL.

    ponytail: global lock, per-connection caches if throughput matters.
    """

    def __init__(self, maxsize: int = 256, ttl: int = 60) -> None:
        self._maxsize = maxsize
        self._ttl = ttl  # seconds
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def _key(self, connection_id: str, database: str, sql: str) -> str:
        return f"{connection_id}:{database}:{sql}"

    def get(self, connection_id: str, database: str, sql: str) -> Any | None:
        key = self._key(connection_id, database, sql)
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def set(self, connection_id: str, database: str, sql: str, value: Any) -> None:
        key = self._key(connection_id, database, sql)
        self._cache[key] = (time.monotonic(), value)
        self._cache.move_to_end(key)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)

    def invalidate(self, connection_id: str | None = None, database: str | None = None) -> None:
        """Invalidate cache entries, optionally filtered by connection/database."""
        if connection_id is None and database is None:
            self._cache.clear()
            return
        to_delete = []
        for key in self._cache:
            parts = key.split(":")
            if connection_id and parts[0] != connection_id:
                continue
            if database and len(parts) > 1 and parts[1] != database:
                continue
            to_delete.append(key)
        for key in to_delete:
            del self._cache[key]

    @property
    def size(self) -> int:
        return len(self._cache)


query_cache = QueryCache()
