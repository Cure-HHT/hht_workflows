"""Resolve each requirement's URS section number.

Which section of the URS a requirement appears in is a rule the URS
generator already owns, and it is not a property of the requirement's
source file alone: a sponsor-scoped chapter lists the same files the core
chapters do and collects the other namespace's requirements from them. So
this module holds no chapter structure and no routing rule of its own --
it loads the consuming repo's URS manifest with the URS generator's own
validated loader and asks that generator's ``section_index`` for the
mapping. Two implementations of the routing would drift; the one that
produces the document is the one that must answer here.

The sibling package is reached by path rather than by installation
because neither generator is packaged -- both entrypoints already put
their own directory on ``sys.path`` the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

_URS_COMPILE_DIR = Path(__file__).resolve().parent.parent.parent / "urs-compile"
if str(_URS_COMPILE_DIR) not in sys.path:
    sys.path.insert(0, str(_URS_COMPILE_DIR))

from urs_compile.graph_loader import Graph  # noqa: E402
from urs_compile.manifest import Manifest as UrsManifest  # noqa: E402
from urs_compile.ordering import section_index  # noqa: E402


def resolve_urs_manifest_path(
    declared: str, oq_manifest_path: Path, primary_root: Path | None = None
) -> Path:
    """Locate the URS manifest the OQ manifest declares.

    ``declared`` is repo-relative, as every other path in the consuming
    repo's manifests is. ``primary_root`` names that repo when the caller
    knows it (the entrypoint does); otherwise the OQ manifest's own
    directory and its parents are searched, which reaches the repo root
    from any manifest location.

    A declared path that resolves to nothing raises: the consumer asked
    for the column, so a silently blank one would be a wrong answer in a
    regulatory report. Declaring nothing at all is the supported way to
    have no column.
    """
    if primary_root is not None:
        candidate = Path(primary_root) / declared
        if candidate.is_file():
            return candidate
        raise ValueError(
            f"URS manifest declared by {oq_manifest_path} as {declared!r} "
            f"does not exist under the primary repository root "
            f"{primary_root}"
        )
    base = Path(oq_manifest_path).resolve().parent
    for directory in [base, *base.parents]:
        candidate = directory / declared
        if candidate.is_file():
            return candidate
    raise ValueError(
        f"URS manifest declared by {oq_manifest_path} as {declared!r} was "
        f"not found in {base} or any parent directory"
    )


def section_numbers(urs_manifest_path: Path, graph_path: Path) -> dict[str, str]:
    """Map requirement id to URS section number ("4.3").

    Requirements the URS places in no section are absent from the mapping;
    the report leaves their cell empty rather than guessing.
    """
    manifest = UrsManifest.from_yaml_path(Path(urs_manifest_path))
    graph = Graph.from_json_path(Path(graph_path))
    return section_index(graph, manifest)
