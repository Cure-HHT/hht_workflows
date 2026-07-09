"""Tests for generated standalone appendices (e.g. the event catalog): parsed
from the manifest, appended to the URS back-matter, and assembled standalone."""
import importlib.util
from pathlib import Path

import pytest


def _load_orchestrator():
    spec_path = Path(__file__).parents[1] / "compile-urs.py"
    spec = importlib.util.spec_from_file_location("compile_urs", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest_dict():
    return {
        "document": {},
        "levels": ["PRD"],
        "appendices": "spec/URS-manifest/appendices.md",
        "standalone_appendices": [
            {
                "file": "docs/reference/event-catalog.md",
                "slug": "event-catalog",
                "title": "Appendix: Event Catalog",
            }
        ],
        "chapters": [
            {"number": 4, "title": "PLATFORM",
             "sections": [{"number": "4.1", "title": "S", "files": []}]},
        ],
    }


def _write_primary(tmp_path: Path, *, catalog_has_h1: bool) -> Path:
    (tmp_path / "spec/URS-manifest").mkdir(parents=True)
    (tmp_path / "spec/URS-manifest/appendices.md").write_text(
        "# Appendices\n\nStandard appendix prose.\n"
    )
    (tmp_path / "docs/reference").mkdir(parents=True)
    body = "CATALOG_CONTENT_MARKER — entry types and actions.\n"
    text = ("# Event catalog (generated)\n\n" + body) if catalog_has_h1 else body
    (tmp_path / "docs/reference/event-catalog.md").write_text(text)
    return tmp_path


def test_manifest_parses_standalone_appendices():
    from urs_compile.manifest import Manifest

    m = Manifest.from_dict(_manifest_dict())
    assert len(m.standalone_appendices) == 1
    sa = m.standalone_appendices[0]
    assert sa.file == "docs/reference/event-catalog.md"
    assert sa.slug == "event-catalog"
    assert sa.title == "Appendix: Event Catalog"


def test_manifest_standalone_appendix_requires_file_and_slug():
    from urs_compile.manifest import Manifest

    with pytest.raises(ValueError):
        Manifest.from_dict({
            "document": {}, "chapters": [],
            "standalone_appendices": [{"title": "no file or slug"}],
        })


def test_standalone_appendix_appended_to_urs_after_appendices(tmp_path):
    from urs_compile.graph_loader import Graph
    from urs_compile.manifest import Manifest

    mod = _load_orchestrator()
    primary = _write_primary(tmp_path, catalog_has_h1=False)
    graph = Graph.from_dict({"nodes": {}})
    manifest = Manifest.from_dict(_manifest_dict())

    out = mod.assemble_full_document(graph, manifest, primary)

    assert "CATALOG_CONTENT_MARKER" in out
    # Title injected because the fixture has no leading H1.
    assert "# Appendix: Event Catalog" in out
    # Ordering: the manifest appendices prose precedes the generated catalog.
    assert out.find("Standard appendix prose") < out.find("CATALOG_CONTENT_MARKER")


def test_standalone_appendix_title_overrides_files_own_h1(tmp_path):
    from urs_compile.graph_loader import Graph
    from urs_compile.manifest import Manifest

    mod = _load_orchestrator()
    primary = _write_primary(tmp_path, catalog_has_h1=True)
    graph = Graph.from_dict({"nodes": {}})
    manifest = Manifest.from_dict(_manifest_dict())

    out = mod.assemble_full_document(graph, manifest, primary)
    # The manifest title governs a generated appendix; the file's own H1 (which
    # the consumer doesn't control) is dropped.
    assert "# Appendix: Event Catalog" in out
    assert "# Event catalog (generated)" not in out
    assert "CATALOG_CONTENT_MARKER" in out


def test_standalone_appendix_missing_file_raises_in_urs(tmp_path):
    from urs_compile.graph_loader import Graph
    from urs_compile.manifest import Manifest

    mod = _load_orchestrator()
    (tmp_path / "spec/URS-manifest").mkdir(parents=True)
    (tmp_path / "spec/URS-manifest/appendices.md").write_text("# Appendices\n")
    # docs/reference/event-catalog.md intentionally NOT created — a declared
    # deliverable that can't resolve must hard-fail, not silently vanish.
    graph = Graph.from_dict({"nodes": {}})
    manifest = Manifest.from_dict(_manifest_dict())
    with pytest.raises(FileNotFoundError):
        mod.assemble_full_document(graph, manifest, tmp_path)


def test_assemble_standalone_appendix_is_self_contained(tmp_path):
    from urs_compile.manifest import Manifest

    mod = _load_orchestrator()
    primary = _write_primary(tmp_path, catalog_has_h1=False)
    manifest = Manifest.from_dict(_manifest_dict())
    sa = manifest.standalone_appendices[0]

    md = mod.assemble_standalone_appendix(sa, primary, None, "pdf")
    assert md.startswith("# Appendix: Event Catalog")
    assert "CATALOG_CONTENT_MARKER" in md


def test_assemble_standalone_appendix_missing_file_returns_none(tmp_path):
    from urs_compile.manifest import Manifest

    mod = _load_orchestrator()
    (tmp_path / "spec/URS-manifest").mkdir(parents=True)
    manifest = Manifest.from_dict(_manifest_dict())
    sa = manifest.standalone_appendices[0]  # file not created

    assert mod.assemble_standalone_appendix(sa, tmp_path, None, "pdf") is None
