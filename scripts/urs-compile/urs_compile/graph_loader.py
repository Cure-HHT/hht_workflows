"""Load elspais `graph` JSON into a typed Graph object."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

#: FILE node ids are ``file:<NAMESPACE>:<relative_path>`` under federation --
#: the namespace segment is the REQ-id prefix of the repo the file came from
#: (``DIARY`` for the platform, ``SPN`` for a sponsor overlay).
_FILE_ID_RE = re.compile(r"^file:([A-Z][A-Z0-9]*):")


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    label: str
    content: dict[str, Any]
    children: tuple[str, ...]
    edges: tuple[dict[str, Any], ...]


class Graph:
    def __init__(self, nodes: dict[str, GraphNode], metadata: dict[str, Any]):
        self._nodes = nodes
        self.metadata = metadata

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Graph":
        nodes: dict[str, GraphNode] = {}
        for node_id, raw in d.get("nodes", {}).items():
            nodes[node_id] = GraphNode(
                id=raw["id"],
                kind=raw["kind"],
                label=raw.get("label", ""),
                content=raw.get("content", {}),
                children=tuple(raw.get("children", [])),
                edges=tuple(raw.get("edges", [])),
            )
        return cls(nodes, d.get("metadata", {}))

    @classmethod
    def from_json_path(cls, path: Path) -> "Graph":
        return cls.from_dict(json.loads(path.read_text()))

    def get_node(self, node_id: str) -> GraphNode:
        return self._nodes[node_id]

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def files_for_relative_path(self, relpath: str) -> list[GraphNode]:
        """Return every FILE node for `relpath` -- one per federated repo.

        A sponsor overlay and the platform file it overlays share one
        relative path, so a federated graph holds a FILE node per repo
        (``file:SPN:spec/prd-rbac.md`` and ``file:DIARY:spec/prd-rbac.md``).
        Callers that want one repo's view filter on :meth:`file_namespace`.
        """
        return [
            n for n in self._nodes.values()
            if n.kind == "FILE" and n.content.get("relative_path") == relpath
        ]

    @staticmethod
    def file_namespace(file_node: GraphNode) -> str:
        """Return the REQ-id namespace of the repo a FILE node came from.

        ``file:SPN:spec/prd-rbac.md`` -> ``"SPN"``. elspais namespaces every
        FILE id, federated or not. An id without one means the graph came
        from a version this pipeline does not support, so raise: callers
        filter a section's prose on this, and guessing would silently drop
        the prose or attribute it to the wrong repo.
        """
        m = _FILE_ID_RE.match(file_node.id)
        if m is None:
            raise ValueError(
                f"FILE node id carries no namespace segment: {file_node.id!r} "
                "(expected 'file:<NAMESPACE>:<relative_path>')"
            )
        return m.group(1)

    def iter_children(self, file_node: GraphNode) -> Iterable[GraphNode]:
        for cid in file_node.children:
            if cid in self._nodes:
                yield self._nodes[cid]

    def requirements_for_source_file(self, relpath: str) -> list[GraphNode]:
        """Return REQUIREMENT nodes whose `source_file` matches `relpath`.

        REQUIREMENT nodes carry their own `source_file` field, so this
        method reaches every repo's REQs for a path in one call, without
        walking the per-repo FILE nodes `relpath` resolves to.
        """
        return [
            n for n in self._nodes.values()
            if n.kind == "REQUIREMENT" and n.content.get("source_file") == relpath
        ]

    def requirement_source_files(self) -> list[str]:
        """Distinct source_file values across REQUIREMENT nodes, first-seen order."""
        seen: set[str] = set()
        out: list[str] = []
        for n in self._nodes.values():
            if n.kind == "REQUIREMENT":
                sf = n.content.get("source_file")
                if sf and sf not in seen:
                    seen.add(sf)
                    out.append(sf)
        return out
