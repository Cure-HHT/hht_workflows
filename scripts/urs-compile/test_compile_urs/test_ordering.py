import pytest

from urs_compile.graph_loader import Graph
from urs_compile.ordering import (
    kebab_topic,
    ordered_section_requirements,
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


def test_kebab_topic_is_first_segment():
    assert kebab_topic("user-account-create") == "user"
    assert kebab_topic("rbac") == "rbac"


def test_core_scope_emits_only_core_namespace():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("CAL-PRD-foo-configuration", parse_line=20),
    )
    ids = [n.id for n in ordered_section_requirements(g, ["spec/x.md"], scope="core")]
    assert ids == ["DIARY-PRD-foo"]


def test_sponsor_scope_emits_only_sponsor_namespace():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("CAL-PRD-foo-configuration", parse_line=20),
        _req("CAL-GUI-bar-modal", parse_line=30),
    )
    ids = [n.id for n in ordered_section_requirements(g, ["spec/x.md"], scope="sponsor")]
    assert ids == ["CAL-PRD-foo-configuration", "CAL-GUI-bar-modal"]


def test_non_urs_levels_excluded():
    g = _graph(
        _req("DIARY-PRD-foo", parse_line=10),
        _req("DIARY-BASE-foo-pin", parse_line=20),
        _req("DIARY-OPS-foo-rotation", parse_line=30),
        _req("DIARY-DEV-foo-schema", parse_line=40),
        _req("DIARY-GUI-foo", parse_line=50),
    )
    ids = [n.id for n in ordered_section_requirements(g, ["spec/x.md"], scope="core")]
    assert ids == ["DIARY-PRD-foo", "DIARY-GUI-foo"]


def test_prd_precedes_gui_within_topic():
    # GUI REQ appears first in the source; PRD of the same topic must
    # still come first in the URS ordering.
    g = _graph(
        _req("DIARY-GUI-user-management-tabs", parse_line=10),
        _req("DIARY-PRD-user-account-create", parse_line=20),
        _req("DIARY-PRD-user-account-edit", parse_line=30),
    )
    ids = [n.id for n in ordered_section_requirements(g, ["spec/x.md"], scope="core")]
    assert ids == [
        "DIARY-PRD-user-account-create",
        "DIARY-PRD-user-account-edit",
        "DIARY-GUI-user-management-tabs",
    ]


def test_topics_keep_first_appearance_order():
    # Topics are NOT alphabetized — the source narrative order survives
    # (foundational REQs stay first).
    g = _graph(
        _req("DIARY-PRD-questionnaire-system", parse_line=10),
        _req("DIARY-PRD-epistaxis-capture-standard", parse_line=20),
    )
    ids = [n.id for n in ordered_section_requirements(g, ["spec/x.md"], scope="core")]
    assert ids == [
        "DIARY-PRD-questionnaire-system",
        "DIARY-PRD-epistaxis-capture-standard",
    ]


def test_source_order_preserved_within_topic_and_level():
    # prd-user-account.md orders the lifecycle create -> edit -> deactivate;
    # the stable sort must not alphabetize the subtopics.
    g = _graph(
        _req("DIARY-PRD-user-account-create", parse_line=10),
        _req("DIARY-PRD-user-account-site-assignment", parse_line=20),
        _req("DIARY-PRD-user-account-edit", parse_line=30),
    )
    ids = [n.id for n in ordered_section_requirements(g, ["spec/x.md"], scope="core")]
    assert ids == [
        "DIARY-PRD-user-account-create",
        "DIARY-PRD-user-account-site-assignment",
        "DIARY-PRD-user-account-edit",
    ]


def test_gui_groups_with_its_topic_not_at_section_end():
    # Topic interleaving: each topic's GUI REQs follow that topic's PRD
    # REQs, before the next topic begins.
    g = _graph(
        _req("DIARY-PRD-password-requirements", parse_line=10),
        _req("DIARY-PRD-two-factor-authentication", parse_line=20),
        _req("DIARY-PRD-password-forgot", parse_line=30),
        _req("DIARY-GUI-password-forgot-workflow", parse_line=40),
        _req("DIARY-PRD-session-management", parse_line=50),
    )
    ids = [n.id for n in ordered_section_requirements(g, ["spec/x.md"], scope="core")]
    assert ids == [
        "DIARY-PRD-password-requirements",
        "DIARY-PRD-password-forgot",
        "DIARY-GUI-password-forgot-workflow",
        "DIARY-PRD-two-factor-authentication",
        "DIARY-PRD-session-management",
    ]


def test_multiple_files_collected_in_manifest_order():
    g = _graph(
        _req("CAL-PRD-zeta-configuration", "spec/a.md", parse_line=10),
        _req("CAL-PRD-alpha-configuration", "spec/b.md", parse_line=10),
    )
    ids = [
        n.id
        for n in ordered_section_requirements(
            g, ["spec/a.md", "spec/b.md"], scope="sponsor"
        )
    ]
    # File order (manifest order) wins over alphabetical topic order.
    assert ids == ["CAL-PRD-zeta-configuration", "CAL-PRD-alpha-configuration"]


def test_section_remainders_walks_file_children(sample_graph_dict):
    g = Graph.from_dict(sample_graph_dict)
    rems = section_remainders(g, ["spec/prd-rbac.md"])
    ids = [r.id for r in rems]
    assert ids == ["rem:spec/prd-rbac.md:1", "rem:spec/prd-rbac.md:2"]
