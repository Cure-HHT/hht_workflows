import pytest

from urs_compile.graph_loader import Graph
from urs_compile.ordering import (
    grouped_section_requirements,
    parse_req_id,
    section_remainders,
)


def _req(req_id: str, source_file: str = "spec/x.md", parse_line: int = 0) -> dict:
    return {
        "id": req_id, "kind": "REQUIREMENT", "label": req_id,
        "content": {"source_file": source_file, "parse_line": parse_line},
        "children": [], "edges": [],
    }


def _graph(*reqs: dict, extra_nodes: dict | None = None) -> Graph:
    nodes = {r["id"]: r for r in reqs}
    nodes.update(extra_nodes or {})
    return Graph.from_dict({"nodes": nodes, "roots": [], "metadata": {}})


def _ids(groups):
    return [[n.id for n in group] for group in groups]


def test_parse_req_id_splits_namespace_level_name():
    assert parse_req_id("DIARY-PRD-user-account-create") == (
        "DIARY", "PRD", "user-account-create"
    )
    assert parse_req_id("CAL-GUI-trial-start-workflow") == (
        "CAL", "GUI", "trial-start-workflow"
    )


def test_parse_req_id_rejects_non_req_ids():
    assert parse_req_id("rem:spec/foo.md:1") is None
    assert parse_req_id("not-a-req") is None


def test_core_scope_emits_only_core_namespace():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("CAL-PRD-foo-configuration", parse_line=20),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="core")
    assert _ids(groups) == [["DIARY-PRD-foo"]]


def test_sponsor_scope_emits_only_sponsor_namespace():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("CAL-PRD-foo-configuration", parse_line=20),
        _req("CAL-GUI-bar-modal", parse_line=30),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="sponsor")
    assert _ids(groups) == [["CAL-PRD-foo-configuration"], ["CAL-GUI-bar-modal"]]


def test_non_urs_levels_excluded():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("DIARY-BASE-foo-pin", parse_line=20),
        _req("DIARY-OPS-foo-rotation", parse_line=30),
        _req("DIARY-DEV-foo-schema", parse_line=40),
        _req("DIARY-GUI-bar", parse_line=50),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="core")
    assert _ids(groups) == [["DIARY-PRD-foo"], ["DIARY-GUI-bar"]]


def test_matching_kebab_names_merge_into_one_group():
    # PRD/GUI twins sharing one kebab name form a single level-3 section,
    # at the position of the FIRST twin, PRD first.
    g = _graph(
        _req("DIARY-PRD-user-account-deactivate", parse_line=10),
        _req("DIARY-PRD-user-account-reactivate", parse_line=20),
        _req("DIARY-GUI-user-management-tabs", parse_line=30),
        _req("DIARY-GUI-user-account-deactivate", parse_line=40),
        _req("DIARY-GUI-user-account-reactivate", parse_line=50),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="core")
    assert _ids(groups) == [
        ["DIARY-PRD-user-account-deactivate", "DIARY-GUI-user-account-deactivate"],
        ["DIARY-PRD-user-account-reactivate", "DIARY-GUI-user-account-reactivate"],
        ["DIARY-GUI-user-management-tabs"],
    ]


def test_prd_precedes_gui_within_group_regardless_of_source_order():
    g = _graph(
        _req("DIARY-GUI-user-authentication", parse_line=10),
        _req("DIARY-PRD-user-authentication", parse_line=20),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="core")
    assert _ids(groups) == [
        ["DIARY-PRD-user-authentication", "DIARY-GUI-user-authentication"],
    ]


def test_non_matching_names_keep_source_order():
    # No reordering beyond the merge: distinct names stay in source order
    # (password-forgot and password-forgot-workflow are different names —
    # only EXACT matches merge).
    g = _graph(
        _req("DIARY-PRD-password-requirements", parse_line=10),
        _req("DIARY-PRD-two-factor-authentication", parse_line=20),
        _req("DIARY-PRD-password-forgot", parse_line=30),
        _req("DIARY-GUI-password-forgot-workflow", parse_line=40),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="core")
    assert _ids(groups) == [
        ["DIARY-PRD-password-requirements"],
        ["DIARY-PRD-two-factor-authentication"],
        ["DIARY-PRD-password-forgot"],
        ["DIARY-GUI-password-forgot-workflow"],
    ]


def test_multiple_files_collected_in_manifest_order():
    g = _graph(
        _req("CAL-PRD-zeta-configuration", "spec/a.md", parse_line=10),
        _req("CAL-PRD-alpha-configuration", "spec/b.md", parse_line=10),
    )
    groups = grouped_section_requirements(
        g, ["spec/a.md", "spec/b.md"], scope="sponsor"
    )
    assert _ids(groups) == [
        ["CAL-PRD-zeta-configuration"], ["CAL-PRD-alpha-configuration"],
    ]


def test_section_remainders_walks_file_children(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    rems = section_remainders(g, ["spec/prd-rbac.md"])
    ids = [r.id for r in rems]
    assert ids == ["rem:spec/prd-rbac.md:1", "rem:spec/prd-rbac.md:2"]


def test_grouped_respects_explicit_levels():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("DIARY-DEV-foo-schema", parse_line=20),
        _req("DIARY-GUI-bar", parse_line=30),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="core", levels=("DEV",))
    assert _ids(groups) == [["DIARY-DEV-foo-schema"]]


def test_grouped_levels_default_is_prd_gui():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("DIARY-DEV-foo-schema", parse_line=20),
        _req("DIARY-GUI-bar", parse_line=30),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="core")
    assert _ids(groups) == [["DIARY-PRD-foo"], ["DIARY-GUI-bar"]]
