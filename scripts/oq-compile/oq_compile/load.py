"""Parse the elspais outputs the report is built from.

Two inputs, because neither carries what the other does: `elspais trace
--values ... --format json` states every requirement with its test-verification
figures and its validating journeys and their verdicts, but not the journeys'
titles; `elspais graph` carries the titles but no verdicts.

The value list is named explicitly rather than selected with `--dimension uat`,
because that dimension suppresses the `verified` and `tested` figures the
test-result column is computed from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_JOURNEY_KIND = "USER_JOURNEY"


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    """Return ``mapping[key]``, or fail loud naming ``ctx``."""
    if key not in mapping or mapping[key] is None:
        raise ValueError(f"{ctx}: required key '{key}' is missing")
    return mapping[key]


@dataclass(frozen=True)
class JourneyRef:
    id: str
    verdict: str


@dataclass(frozen=True)
class Requirement:
    """One requirement row, carrying both kinds of evidence.

    ``uat_verified_ratio`` and ``journeys`` are the user-acceptance evidence;
    ``verified_ratio``, ``verified_carried`` and ``tested_failed`` are the
    test-verification evidence. They are kept apart, never combined, because
    the report states them in separate columns: a reader must be able to see
    which kind of evidence is missing, which a single rolled-up verdict hides.
    """

    id: str
    title: str
    level: str
    status: str
    uat_verified_ratio: float
    verified_ratio: float
    verified_carried: bool
    tested_failed: float
    journeys: tuple[JourneyRef, ...]


def _dedupe(raw: list[dict[str, Any]]) -> tuple[JourneyRef, ...]:
    """Collapse repeated entries for one journey, preserving first order.

    A requirement validated by one journey across several assertions is
    reported once per assertion in some elspais renderings. The report states
    a journey once per requirement, so the first entry wins.
    """
    seen: dict[str, JourneyRef] = {}
    for i, entry in enumerate(raw):
        jid = _require(entry, "id", f"journey entry {i}")
        if jid not in seen:
            seen[jid] = JourneyRef(id=jid, verdict=entry.get("verdict", "unverified"))
    return tuple(seen.values())


def load_trace(path: Path) -> tuple[tuple[Requirement, ...], tuple[str, ...]]:
    """Return the requirements and the scope header lines.

    Accepts both shapes the trace exporter emits: a bare list of requirement
    objects (no scope named), and a mapping carrying a `scope` header
    alongside the requirement rows under `nodes` (scope named). Manifests
    that declare a scope -- the normal production case -- always take the
    dict path, so a wrong key there is not a corner case.

    A dict that carries none of the recognised rows keys raises rather than
    falling back to an empty list: this loader once treated `requirements`/
    `rows` as the dict's rows key, which does not exist in real
    `elspais trace` output (the real key is `nodes`), and silently rendered
    a well-formed, empty compliance report under any scoped manifest. An
    unrecognised shape must abort the run, not render nothing.
    """
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, dict):
        if "nodes" not in raw:
            raise ValueError(
                "trace file is a dict with no recognised rows key "
                f"(expected 'nodes'); keys present: {sorted(raw.keys())}"
            )
        rows = raw["nodes"]
        scope = tuple(raw.get("scope") or ())
    else:
        rows = raw
        scope = ()

    requirements = tuple(
        Requirement(
            id=_require(row, "id", f"requirement row {i}"),
            title=row.get("title", ""),
            level=row.get("level", ""),
            status=row.get("status", ""),
            uat_verified_ratio=float(
                _require(
                    _require(row, "uat_verified", f"requirement row {i}"),
                    "ratio",
                    f"requirement row {i}: uat_verified",
                )
            ),
            # `verified.ratio`, `verified.carried` and `tested.failed` are all
            # read with `_require`: each one, absent, would silently overstate
            # the evidence. A missing `failed` renders a failing requirement as
            # NOT RUN, and a missing `carried` renders a carried baseline as a
            # fresh run -- the stronger claim in both cases. Contrast the
            # tolerant `verdict` default above, which falls back to
            # "unverified", the weaker claim, and so is safe to default.
            verified_ratio=float(
                _require(
                    _require(row, "verified", f"requirement row {i}"),
                    "ratio",
                    f"requirement row {i}: verified",
                )
            ),
            verified_carried=bool(
                _require(
                    _require(row, "verified", f"requirement row {i}"),
                    "carried",
                    f"requirement row {i}: verified",
                )
            ),
            tested_failed=float(
                _require(
                    _require(row, "tested", f"requirement row {i}"),
                    "failed",
                    f"requirement row {i}: tested",
                )
            ),
            journeys=_dedupe(_require(row, "journeys", f"requirement row {i}")),
        )
        for i, row in enumerate(rows)
    )
    return requirements, scope


def load_journeys(path: Path, cited_journeys: int = 0) -> dict[str, str]:
    """Map journey id to title from a graph export.

    The graph export carries every node kind; only USER_JOURNEY nodes are
    retained. `elspais graph` offers no filter flag, so the whole export is
    read and narrowed here.

    ``cited_journeys`` is how many journey citations the trace carried. It is
    known only to the caller, which has both inputs in hand, so it is threaded
    in rather than inferred here. When the trace cites at least one journey and
    the graph yields no journey node at all, the narrowing above matched
    nothing — a changed export shape or a renamed node-kind string — and every
    UAT row would render with a blank Description. That is a silent, plausible,
    wrong report, so it aborts.
    """
    raw = json.loads(Path(path).read_text())
    nodes = raw.get("nodes") or {}
    entries = nodes.values() if isinstance(nodes, dict) else nodes
    titles = {
        node["id"]: node.get("label", "")
        for node in entries
        if node.get("kind") == _JOURNEY_KIND
    }
    if cited_journeys and not titles:
        kinds = sorted({str(node.get("kind")) for node in entries})
        raise ValueError(
            f"graph '{path}' yields no '{_JOURNEY_KIND}' node while the trace "
            f"cites {cited_journeys} journey reference(s); every UAT row would "
            f"carry a blank description. Node kinds present: {kinds}"
        )
    return titles
