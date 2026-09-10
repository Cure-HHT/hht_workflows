"""Parse the elspais outputs the report is built from.

Two inputs, because neither carries what the other does: `elspais trace
--dimension uat --format json` states every requirement with its validating
journeys and their verdicts but not the journeys' titles, and `elspais graph`
carries the titles but no verdicts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_JOURNEY_KIND = "USER_JOURNEY"


@dataclass(frozen=True)
class JourneyRef:
    id: str
    verdict: str


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    level: str
    status: str
    uat_verified_ratio: float
    journeys: tuple[JourneyRef, ...]


def _dedupe(raw: list[dict[str, Any]]) -> tuple[JourneyRef, ...]:
    """Collapse repeated entries for one journey, preserving first order.

    A requirement validated by one journey across several assertions is
    reported once per assertion in some elspais renderings. The report states
    a journey once per requirement, so the first entry wins.
    """
    seen: dict[str, JourneyRef] = {}
    for entry in raw:
        jid = entry["id"]
        if jid not in seen:
            seen[jid] = JourneyRef(id=jid, verdict=entry.get("verdict", "unverified"))
    return tuple(seen.values())


def load_trace(path: Path) -> tuple[tuple[Requirement, ...], tuple[str, ...]]:
    """Return the requirements and the scope header lines.

    Accepts both shapes the trace exporter emits: a bare list of requirements,
    and a mapping carrying a `scope` header alongside them. The header is
    absent when no scope was named, so an empty tuple is a valid answer and
    not a parse failure.
    """
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, dict):
        rows = raw.get("requirements") or raw.get("rows") or []
        scope = tuple(raw.get("scope") or ())
    else:
        rows = raw
        scope = ()

    requirements = tuple(
        Requirement(
            id=row["id"],
            title=row.get("title", ""),
            level=row.get("level", ""),
            status=row.get("status", ""),
            uat_verified_ratio=float((row.get("uat_verified") or {}).get("ratio", 0.0)),
            journeys=_dedupe(row.get("journeys") or []),
        )
        for row in rows
    )
    return requirements, scope


def load_journeys(path: Path) -> dict[str, str]:
    """Map journey id to title from a graph export.

    The graph export carries every node kind; only USER_JOURNEY nodes are
    retained. `elspais graph` offers no filter flag, so the whole export is
    read and narrowed here.
    """
    raw = json.loads(Path(path).read_text())
    nodes = raw.get("nodes") or {}
    entries = nodes.values() if isinstance(nodes, dict) else nodes
    return {
        node["id"]: node.get("label", "")
        for node in entries
        if node.get("kind") == _JOURNEY_KIND
    }
