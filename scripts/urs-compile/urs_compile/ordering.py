"""Group section REQs by their kebab ID name into URS level-3 sections.

The URS body no longer interleaves sponsor (CAL-*) REQs with core
(DIARY-*) REQs. Each manifest chapter declares a ``scope`` — ``core``
chapters emit only core-namespace REQs, the ``sponsor`` chapter collects
every sponsor-namespace REQ from the files it references.

Within a section, REQs whose IDs share the same kebab name after the
namespace/level prefix (``DIARY-PRD-user-account-deactivate`` and
``DIARY-GUI-user-account-deactivate``) merge into a single level-3
section: one numbered heading, the PRD REQ first, the GUI REQ following
in the same section (no page break between them). This removes the
duplicate titles the TOC otherwise shows for PRD/GUI twins. Groups keep
the source (parse_line) order of their first member; within a group,
PRD precedes GUI.

Only URS-relevant levels (PRD, GUI) are emitted. BASE / OPS / DEV REQs
in manifest-referenced files are excluded from the URS deliverable.
"""

from __future__ import annotations

import re
from typing import Iterable

from .graph_loader import Graph, GraphNode

_ID_RE = re.compile(r"^([A-Z][A-Z0-9]*)-([A-Z]+)-([a-z0-9][a-z0-9-]*)$")

#: Namespace of the platform (core) repo; anything else is a sponsor overlay.
CORE_NAMESPACE = "DIARY"

#: REQ levels that appear in the URS deliverable, in presentation order.
URS_LEVELS = ("PRD", "GUI")

_LEVEL_RANK = {level: rank for rank, level in enumerate(URS_LEVELS)}


def parse_req_id(req_id: str) -> tuple[str, str, str] | None:
    """Split a REQ id into (namespace, level, kebab-name).

    ``DIARY-PRD-user-account-create`` -> ``("DIARY", "PRD", "user-account-create")``.
    Returns None for ids that don't follow the convention.
    """
    m = _ID_RE.match(req_id)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def grouped_section_requirements(
    graph: Graph,
    relpaths: Iterable[str],
    scope: str = "core",
    levels: tuple[str, ...] = URS_LEVELS,
) -> list[list[GraphNode]]:
    """Return the section's REQs filtered by `scope`, grouped for the URS.

    `scope`:
    - ``"core"`` — REQs in the :data:`CORE_NAMESPACE` only.
    - ``"sponsor"`` — REQs in any other namespace (the sponsor overlay).

    `levels` — the REQ levels to include, in presentation order.  Defaults
    to :data:`URS_LEVELS` (``("PRD", "GUI")``).  Pass a custom tuple to
    include different levels (e.g. ``("DEV",)`` for a dev-only build).

    Each returned group holds the REQs sharing one kebab name and renders
    as one level-3 section. Groups appear in source order (manifest file
    order, then parse_line of the group's first member); group members
    are ordered by level rank within the supplied `levels` tuple (stable
    sort, so source order breaks ties).
    """
    level_rank = {lvl: i for i, lvl in enumerate(levels)}

    collected: list[tuple[GraphNode, str, str]] = []
    for relpath in relpaths:
        reqs = graph.requirements_for_source_file(relpath)
        reqs.sort(key=lambda n: n.content.get("parse_line") or 0)
        for req in reqs:
            parsed = parse_req_id(req.id)
            if parsed is None:
                continue
            namespace, level, name = parsed
            if level not in level_rank:
                continue
            if (namespace == CORE_NAMESPACE) != (scope == "core"):
                continue
            collected.append((req, level, name))

    group_order: list[str] = []
    groups: dict[str, list[tuple[GraphNode, str]]] = {}
    for req, level, name in collected:
        if name not in groups:
            groups[name] = []
            group_order.append(name)
        groups[name].append((req, level))

    out: list[list[GraphNode]] = []
    for name in group_order:
        members = sorted(groups[name], key=lambda item: level_rank[item[1]])
        out.append([req for req, _level in members])
    return out


def section_remainders(graph: Graph, relpaths: Iterable[str]) -> list[GraphNode]:
    """Return the surviving FILE node's REMAINDERs for each path, in order.

    REMAINDERs carry the file's title and intro prose. In the spec trees
    all non-empty REMAINDERs precede the first REQ, so emitting them as a
    block before the grouped REQs preserves the rendered prose.
    Federation keeps a single FILE node per relative_path; its repo bias
    decides whose prose survives (pre-existing pipeline behaviour).
    """
    out: list[GraphNode] = []
    for relpath in relpaths:
        out.extend(graph.remainders_for_source_file(relpath))
    return out
