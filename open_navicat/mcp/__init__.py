"""MCP server — OpenNavicat as a callable tool surface for AI clients.

The package is split so the policy and tool layers are testable on their own:

* :mod:`open_navicat.mcp.safety` — three-tier access policy, pure text analysis.
* :mod:`open_navicat.mcp.runner` — one dedicated thread owning the asyncio loop
  that service calls are serialised onto.
* :mod:`open_navicat.mcp.tools` — the tool implementations, SDK-free.
* :mod:`open_navicat.mcp.server` — the ``mcp`` SDK adapter (optional import).

Nothing at package import time touches the ``mcp`` distribution, so
``pip install open-navicat`` without the ``[mcp]`` extra keeps working and
``open_navicat.mcp.safety`` stays importable in a bare environment.
"""

from __future__ import annotations

from open_navicat.mcp.safety import (
    RISK_HIGH,
    RISK_READ,
    RISK_WRITE,
    TIER_CEILING,
    TIER_FULL,
    TIER_READ,
    TIER_SAFE_WRITE,
    TIERS,
    Analysis,
    Decision,
    Statement,
    analyze,
    check,
    classify_statement,
    normalize_tier,
)

__all__ = [
    "Analysis",
    "Decision",
    "RISK_HIGH",
    "RISK_READ",
    "RISK_WRITE",
    "Statement",
    "TIER_CEILING",
    "TIER_FULL",
    "TIER_READ",
    "TIER_SAFE_WRITE",
    "TIERS",
    "analyze",
    "check",
    "classify_statement",
    "normalize_tier",
]
