"""The URS-section column: which section each requirement is reported under.

The routing is the URS generator's, reused rather than reimplemented, so
these exercise the seam: that the OQ report asks that generator for the
answer, that a namespace-routed sponsor section resolves differently from
the core section over the same file, that a requirement in no section
leaves an empty cell, and that a consumer with no URS still gets a report.
"""

from __future__ import annotations

import json

import pytest
import yaml

from oq_compile.load import Requirement
from oq_compile.manifest import Manifest
from oq_compile.pivot import req_rows
from oq_compile.urs_sections import resolve_urs_manifest_path, section_numbers

# One file, carrying a core requirement and a sponsor requirement. The URS
# manifest below routes them to different chapters -- core to 4.3, sponsor
# to 7.1 -- which is why the source file alone cannot name the section.
_GRAPH = {
    "nodes": {
        "DIARY-PRD-roles": {
            "id": "DIARY-PRD-roles", "kind": "REQUIREMENT", "label": "Roles",
            "content": {"source_file": "spec/prd-rbac.md", "parse_line": 10},
            "children": [], "edges": [],
        },
        "SPN-PRD-roles-configuration": {
            "id": "SPN-PRD-roles-configuration", "kind": "REQUIREMENT",
            "label": "Roles Configuration",
            "content": {"source_file": "spec/prd-rbac.md", "parse_line": 20},
            "children": [], "edges": [],
        },
        "DIARY-PRD-unlisted": {
            "id": "DIARY-PRD-unlisted", "kind": "REQUIREMENT", "label": "Unlisted",
            "content": {"source_file": "spec/prd-elsewhere.md", "parse_line": 10},
            "children": [], "edges": [],
        },
        "DIARY-OPS-roles-rotation": {
            "id": "DIARY-OPS-roles-rotation", "kind": "REQUIREMENT",
            "label": "Rotation",
            "content": {"source_file": "spec/prd-rbac.md", "parse_line": 30},
            "children": [], "edges": [],
        },
    },
    "roots": [],
    "metadata": {},
}

_URS_MANIFEST = {
    "document": {"title": "User Requirements Specification"},
    "levels": ["PRD", "GUI"],
    "chapters": [
        {
            "number": 4,
            "title": "SYSTEM-WIDE STANDARDS",
            "sections": [
                {"number": "4.3", "title": "Roles", "files": ["spec/prd-rbac.md"]},
            ],
        },
        {
            "number": 7,
            "title": "SPONSOR CONFIGURATION",
            "scope": "sponsor",
            "sections": [
                {"number": "7.1", "title": "Standards", "files": ["spec/prd-rbac.md"]},
            ],
        },
    ],
}


@pytest.fixture
def urs_inputs(tmp_path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(_GRAPH))
    manifest = tmp_path / "urs.yaml"
    manifest.write_text(yaml.safe_dump(_URS_MANIFEST))
    return manifest, graph


def _oq_manifest(tmp_path, *, urs: str | None) -> Manifest:
    columns = ["Req ID", "Description", "Test Result", "UAT Result", "UAT Test Case ID"]
    if urs is not None:
        columns.insert(1, "URS Section")
    doc = {
        "document": {"title": "OQ", "project": "Example Study"},
        "scope": "example-scope",
        "sheets": {
            "req": {"name": "Requirements", "columns": columns},
            "uat": {
                "name": "UAT Test Cases",
                "columns": [
                    "UAT Test Case ID", "Description", "Pass/Fail",
                    "User Journey ID", "Req ID",
                ],
            },
        },
    }
    if urs is not None:
        doc["urs_manifest"] = urs
    path = tmp_path / "oq.yaml"
    path.write_text(yaml.safe_dump(doc))
    return Manifest.from_path(path)


def _req(req_id: str) -> Requirement:
    return Requirement(
        id=req_id, title=req_id, level="PRD", status="active",
        uat_verified_ratio=0.0, verified_ratio=0.0, verified_carried=False,
        tested_failed=0.0, journeys=(),
    )


def test_core_scoped_section_resolves_the_core_requirement(urs_inputs):
    manifest, graph = urs_inputs
    assert section_numbers(manifest, graph)["DIARY-PRD-roles"] == "4.3"


def test_sponsor_scoped_section_resolves_the_sponsor_requirement(urs_inputs):
    # Same source file as the core requirement above, different section:
    # the namespace, not the file, decides which chapter collects it.
    manifest, graph = urs_inputs
    assert section_numbers(manifest, graph)["SPN-PRD-roles-configuration"] == "7.1"


def test_requirement_in_no_section_is_absent_from_the_mapping(urs_inputs):
    manifest, graph = urs_inputs
    sections = section_numbers(manifest, graph)
    assert "DIARY-PRD-unlisted" not in sections
    # ... as is a requirement whose level the URS excludes, even though its
    # file is listed by a section.
    assert "DIARY-OPS-roles-rotation" not in sections


def test_row_carries_the_section_number_in_the_second_column(tmp_path, urs_inputs):
    urs_manifest, graph = urs_inputs
    manifest = _oq_manifest(tmp_path, urs=str(urs_manifest))
    rows = req_rows(
        (_req("DIARY-PRD-roles"), _req("SPN-PRD-roles-configuration")),
        manifest,
        section_numbers(urs_manifest, graph),
    )
    assert rows[0][:2] == ["DIARY-PRD-roles", "4.3"]
    assert rows[1][:2] == ["SPN-PRD-roles-configuration", "7.1"]


def test_requirement_in_no_section_gets_an_empty_cell(tmp_path, urs_inputs):
    urs_manifest, graph = urs_inputs
    manifest = _oq_manifest(tmp_path, urs=str(urs_manifest))
    rows = req_rows(
        (_req("DIARY-PRD-unlisted"),), manifest, section_numbers(urs_manifest, graph)
    )
    assert rows[0][:3] == ["DIARY-PRD-unlisted", "", "DIARY-PRD-unlisted"]


def test_manifest_without_a_urs_declares_five_columns_and_no_section_cell(tmp_path):
    manifest = _oq_manifest(tmp_path, urs=None)
    assert manifest.urs_manifest is None
    assert manifest.req_section_column is None
    rows = req_rows((_req("DIARY-PRD-roles"),), manifest)
    assert rows[0] == ["DIARY-PRD-roles", "DIARY-PRD-roles", "NOT RUN", "NOT RUN"]


def test_declaring_a_urs_requires_the_extra_column(tmp_path):
    doc = {
        "document": {"title": "OQ", "project": "Example Study"},
        "scope": "example-scope",
        "urs_manifest": "spec/URS-manifest/urs.yaml",
        "sheets": {
            "req": {
                "name": "Requirements",
                "columns": [
                    "Req ID", "Description", "Test Result", "UAT Result",
                    "UAT Test Case ID",
                ],
            },
            "uat": {
                "name": "UAT Test Cases",
                "columns": [
                    "UAT Test Case ID", "Description", "Pass/Fail",
                    "User Journey ID", "Req ID",
                ],
            },
        },
    }
    path = tmp_path / "oq.yaml"
    path.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="must declare exactly 6 columns"):
        Manifest.from_path(path)


def test_manifest_path_resolves_under_the_primary_root(tmp_path):
    root = tmp_path / "repo"
    (root / "spec" / "URS-manifest").mkdir(parents=True)
    target = root / "spec" / "URS-manifest" / "urs.yaml"
    target.write_text("document: {}\n")
    oq = root / "spec" / "OQ-manifest" / "oq.yaml"
    oq.parent.mkdir(parents=True)
    oq.write_text("")
    assert resolve_urs_manifest_path(
        "spec/URS-manifest/urs.yaml", oq, root
    ) == target


def test_manifest_path_resolves_by_walking_up_when_no_root_is_given(tmp_path):
    root = tmp_path / "repo"
    (root / "spec" / "URS-manifest").mkdir(parents=True)
    target = root / "spec" / "URS-manifest" / "urs.yaml"
    target.write_text("document: {}\n")
    oq = root / "spec" / "OQ-manifest" / "oq.yaml"
    oq.parent.mkdir(parents=True)
    oq.write_text("")
    assert resolve_urs_manifest_path("spec/URS-manifest/urs.yaml", oq) == target


def test_a_declared_but_missing_urs_manifest_fails_loud(tmp_path):
    oq = tmp_path / "oq.yaml"
    oq.write_text("")
    with pytest.raises(ValueError, match="urs.yaml"):
        resolve_urs_manifest_path("spec/URS-manifest/urs.yaml", oq, tmp_path)
