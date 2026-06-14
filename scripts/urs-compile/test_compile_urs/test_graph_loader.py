import pytest

from urs_compile.graph_loader import Graph, GraphNode


def test_load_from_dict(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    assert g.get_node("DIARY-PRD-rbac").kind == "REQUIREMENT"
    assert g.get_node("rem:spec/prd-rbac.md:1").kind == "REMAINDER"


def test_files_for_relative_path_returns_surviving_file(sample_graph_dict):
    # Federation collapses FILE nodes sharing a relative_path — only one
    # survives; cross-repo REQs stay reachable via content.source_file.
    g = Graph.from_dict(sample_graph_dict)
    files = g.files_for_relative_path("spec/prd-rbac.md")
    assert len(files) == 1
    assert files[0].content.get("repo") is None


def test_iter_children_yields_in_order(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    file_node = g.get_node("file:spec/prd-rbac.md")
    child_ids = [c.id for c in g.iter_children(file_node)]
    assert child_ids == [
        "rem:spec/prd-rbac.md:1",
        "DIARY-PRD-rbac",
        "DIARY-PRD-action-inventory",
        "DIARY-PRD-role-definitions",
        "rem:spec/prd-rbac.md:2",
        "DIARY-GUI-role-switching",
    ]


def test_get_node_missing_raises():
    g = Graph.from_dict({"nodes": {}, "roots": [], "metadata": {}})
    with pytest.raises(KeyError):
        g.get_node("nonexistent")
