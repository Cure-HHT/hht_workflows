import pytest

from urs_compile.graph_loader import Graph
from urs_compile.manifest import Manifest
from urs_compile.ordering import (
    grouped_section_requirements,
    parse_req_id,
    section_index,
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
    assert parse_req_id("SPN-GUI-trial-start-workflow") == (
        "SPN", "GUI", "trial-start-workflow"
    )


def test_parse_req_id_rejects_non_req_ids():
    assert parse_req_id("rem:spec/foo.md:1") is None
    assert parse_req_id("not-a-req") is None


def test_core_scope_emits_only_core_namespace():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("SPN-PRD-foo-configuration", parse_line=20),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="core")
    assert _ids(groups) == [["DIARY-PRD-foo"]]


def test_sponsor_scope_emits_only_sponsor_namespace():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("SPN-PRD-foo-configuration", parse_line=20),
        _req("SPN-GUI-bar-modal", parse_line=30),
    )
    groups = grouped_section_requirements(g, ["spec/x.md"], scope="sponsor")
    assert _ids(groups) == [["SPN-PRD-foo-configuration"], ["SPN-GUI-bar-modal"]]


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
        _req("SPN-PRD-zeta-configuration", "spec/a.md", parse_line=10),
        _req("SPN-PRD-alpha-configuration", "spec/b.md", parse_line=10),
    )
    groups = grouped_section_requirements(
        g, ["spec/a.md", "spec/b.md"], scope="sponsor"
    )
    assert _ids(groups) == [
        ["SPN-PRD-zeta-configuration"], ["SPN-PRD-alpha-configuration"],
    ]


def test_section_remainders_walks_file_children(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    rems = section_remainders(g, ["spec/prd-rbac.md"])
    ids = [r.id for r in rems]
    assert ids == ["rem:DIARY:spec/prd-rbac.md:1", "rem:DIARY:spec/prd-rbac.md:2"]


def test_section_remainders_excludes_the_overlay_repo_prose(sample_graph_dict):
    # The sponsor overlay shares the relative path, so its FILE node offers
    # prose for the same section. A core section must not render it: doing
    # so puts the overlay's intro under the platform section heading and
    # emits the platform file's own title as a second heading below it.
    g = Graph.from_dict(sample_graph_dict)
    rems = section_remainders(g, ["spec/prd-rbac.md"], scope="core")
    assert "rem:SPN:spec/prd-rbac.md:1" not in [r.id for r in rems]


def test_section_remainders_rejects_a_graph_without_namespaced_file_ids():
    # An un-namespaced FILE id means a graph this pipeline does not support.
    # Failing here is deliberate: guessing would silently drop a section's
    # prose or attribute it to the wrong repo.
    g = Graph.from_dict({
        "nodes": {
            "file:spec/prd-rbac.md": {
                "id": "file:spec/prd-rbac.md", "kind": "FILE",
                "label": "prd-rbac.md",
                "content": {"relative_path": "spec/prd-rbac.md"},
                "children": [], "edges": [],
            },
        },
        "roots": [], "metadata": {},
    })
    with pytest.raises(ValueError, match="no namespace segment"):
        section_remainders(g, ["spec/prd-rbac.md"], scope="core")


def test_section_remainders_sponsor_scope_takes_the_overlay_prose(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    rems = section_remainders(g, ["spec/prd-rbac.md"], scope="sponsor")
    assert [r.id for r in rems] == ["rem:SPN:spec/prd-rbac.md:1"]


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


# --- section_index -------------------------------------------------------


def _manifest(*chapters: dict) -> Manifest:
    return Manifest.from_dict({"document": {}, "levels": ["PRD", "GUI"],
                               "chapters": list(chapters)})


def _chapter(number: int, sections: list[dict], scope: str = "core") -> dict:
    return {"number": number, "title": f"CH{number}", "scope": scope,
            "sections": sections}


def test_section_index_routes_core_and_sponsor_reqs_from_one_file():
    # The sponsor chapter lists the same file the core chapter does and takes
    # the other namespace's REQs from it, so the file alone cannot name the
    # section -- the namespace participates.
    g = _graph(
        _req("DIARY-PRD-roles", "spec/prd-rbac.md", parse_line=10),
        _req("SPN-PRD-roles-configuration", "spec/prd-rbac.md", parse_line=20),
    )
    manifest = _manifest(
        _chapter(4, [{"number": "4.3", "title": "Roles",
                      "files": ["spec/prd-rbac.md"]}]),
        _chapter(7, [{"number": "7.1", "title": "Standards",
                      "files": ["spec/prd-rbac.md"]}], scope="sponsor"),
    )
    assert section_index(g, manifest) == {
        "DIARY-PRD-roles": "4.3",
        "SPN-PRD-roles-configuration": "7.1",
    }


def test_section_index_omits_reqs_no_section_places():
    g = _graph(
        _req("DIARY-PRD-roles", "spec/prd-rbac.md"),
        _req("DIARY-PRD-elsewhere", "spec/prd-elsewhere.md"),
        _req("DIARY-OPS-rotation", "spec/prd-rbac.md"),
    )
    manifest = _manifest(
        _chapter(4, [{"number": "4.3", "title": "Roles",
                      "files": ["spec/prd-rbac.md"]}]),
    )
    assert section_index(g, manifest) == {"DIARY-PRD-roles": "4.3"}


def test_section_index_refuses_a_req_claimed_by_two_sections():
    g = _graph(_req("DIARY-PRD-roles", "spec/prd-rbac.md"))
    manifest = _manifest(
        _chapter(4, [
            {"number": "4.3", "title": "Roles", "files": ["spec/prd-rbac.md"]},
            {"number": "4.9", "title": "Again", "files": ["spec/prd-rbac.md"]},
        ]),
    )
    with pytest.raises(ValueError, match="DIARY-PRD-roles.*4.3 and 4.9"):
        section_index(g, manifest)


def test_section_index_honours_a_section_level_override():
    g = _graph(
        _req("DIARY-PRD-roles", "spec/prd-rbac.md"),
        _req("DIARY-DEV-schema", "spec/prd-rbac.md"),
    )
    manifest = _manifest(
        _chapter(9, [{"number": "9.1", "title": "Implementation",
                      "files": ["spec/prd-rbac.md"], "levels": ["DEV"]}]),
    )
    assert section_index(g, manifest) == {"DIARY-DEV-schema": "9.1"}


def test_section_index_indexes_a_by_level_section_across_the_corpus():
    # A section with levels and no files selects across every source file in
    # the graph, exactly as the document assembler does.
    g = _graph(
        _req("DIARY-PRD-roles", "spec/prd-rbac.md"),
        _req("DIARY-DEV-schema", "spec/dev-schema.md"),
    )
    manifest = _manifest(
        _chapter(9, [{"number": "9.1", "title": "Implementation",
                      "levels": ["DEV"]}]),
    )
    assert section_index(g, manifest) == {"DIARY-DEV-schema": "9.1"}
