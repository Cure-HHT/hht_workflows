"""Order section REQs by their kebab ID structure: topic, level, subtopic.

The URS body no longer interleaves sponsor (CAL-*) REQs with core
(DIARY-*) REQs. Each manifest chapter declares a ``scope`` — ``core``
chapters emit only core-namespace REQs, the ``sponsor`` chapter collects
every sponsor-namespace REQ from the files it references.

Within a section, REQs are ordered by the kebab structure of their IDs.
Given ``DIARY-{PRD|GUI}-{topic}-{subtopic...}``:

1. **topic** — the first kebab segment of the namespace/level-stripped
   name. Topics appear in order of first appearance across the section's
   files (preserving the source narrative: foundational REQs stay first).
2. **level** — PRD before GUI within a topic.
3. **subtopic** — source (parse_line) order within a (topic, level)
   group; the sort is stable so the author's in-file ordering survives.

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


def kebab_topic(name: str) -> str:
    """Return the topic (first kebab segment) of a stripped REQ name."""
    return name.split("-", 1)[0]


def ordered_section_requirements(
    graph: Graph,
    relpaths: Iterable[str],
    scope: str = "core",
) -> list[GraphNode]:
    """Return the section's REQs filtered by `scope`, in URS order.

    `scope`:
    - ``"core"`` — REQs in the :data:`CORE_NAMESPACE` only.
    - ``"sponsor"`` — REQs in any other namespace (the sponsor overlay).

    REQs are collected across `relpaths` in manifest order, then sorted
    by (topic first-appearance, level rank) with a stable sort so source
    order is preserved inside each (topic, level) group.
    """
    collected: list[tuple[GraphNode, str, str]] = []
    for relpath in relpaths:
        reqs = graph.requirements_for_source_file(relpath)
        reqs.sort(key=lambda n: n.content.get("parse_line") or 0)
        for req in reqs:
            parsed = parse_req_id(req.id)
            if parsed is None:
                continue
            namespace, level, name = parsed
            if level not in _LEVEL_RANK:
                continue
            if (namespace == CORE_NAMESPACE) != (scope == "core"):
                continue
            collected.append((req, level, name))

    topic_first_appearance: dict[str, int] = {}
    for _req, _level, name in collected:
        topic_first_appearance.setdefault(kebab_topic(name), len(topic_first_appearance))

    collected.sort(
        key=lambda item: (
            topic_first_appearance[kebab_topic(item[2])],
            _LEVEL_RANK[item[1]],
        )
    )
    return [req for req, _level, _name in collected]


def section_remainders(graph: Graph, relpaths: Iterable[str]) -> list[GraphNode]:
    """Return the surviving FILE node's REMAINDERs for each path, in order.

    REMAINDERs carry the file's title and intro prose. In the spec trees
    all non-empty REMAINDERs precede the first REQ, so emitting them as a
    block before the re-ordered REQs preserves the rendered prose.
    Federation keeps a single FILE node per relative_path; its repo bias
    decides whose prose survives (pre-existing pipeline behaviour).
    """
    out: list[GraphNode] = []
    for relpath in relpaths:
        out.extend(graph.remainders_for_source_file(relpath))
    return out
