import pytest

from urs_compile.graph_loader import Graph, GraphNode


def test_load_from_dict(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    assert g.get_node("DIARY-PRD-rbac").kind == "REQUIREMENT"
    assert g.get_node("rem:DIARY:spec/prd-rbac.md:1").kind == "REMAINDER"


def test_files_for_relative_path_returns_one_file_per_repo(sample_graph_dict):
    # A sponsor overlay and the platform file it overlays share a relative
    # path; federation keeps both FILE nodes, one per repo namespace.
    g = Graph.from_dict(sample_graph_dict)
    files = g.files_for_relative_path("spec/prd-rbac.md")
    assert {f.id for f in files} == {
        "file:DIARY:spec/prd-rbac.md", "file:SPN:spec/prd-rbac.md",
    }


def test_file_namespace_reads_the_id_segment(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    assert g.file_namespace(g.get_node("file:SPN:spec/prd-rbac.md")) == "SPN"
    assert g.file_namespace(g.get_node("file:DIARY:spec/prd-rbac.md")) == "DIARY"


def test_file_namespace_is_none_on_a_pre_namespacing_graph():
    node = GraphNode(
        id="file:spec/prd-rbac.md", kind="FILE", label="prd-rbac.md",
        content={"relative_path": "spec/prd-rbac.md"}, children=(), edges=(),
    )
    assert Graph({}, {}).file_namespace(node) is None


def test_iter_children_yields_in_order(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    file_node = g.get_node("file:DIARY:spec/prd-rbac.md")
    child_ids = [c.id for c in g.iter_children(file_node)]
    assert child_ids == [
        "rem:DIARY:spec/prd-rbac.md:1",
        "DIARY-PRD-rbac",
        "DIARY-PRD-action-inventory",
        "DIARY-PRD-role-definitions",
        "rem:DIARY:spec/prd-rbac.md:2",
        "DIARY-GUI-role-switching",
    ]


def test_get_node_missing_raises():
    g = Graph.from_dict({"nodes": {}, "roots": [], "metadata": {}})
    with pytest.raises(KeyError):
        g.get_node("nonexistent")
