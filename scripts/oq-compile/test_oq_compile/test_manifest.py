from __future__ import annotations

import pytest

from oq_compile.manifest import Manifest


def test_loads_document_identity(sample_manifest_path):
    m = Manifest.from_path(sample_manifest_path)
    assert m.title == "Operational Qualification — Traceability Report"
    assert m.project == "Example Study"


def test_loads_scope_and_prefix(sample_manifest_path):
    m = Manifest.from_path(sample_manifest_path)
    assert m.scope == "example-scope"
    assert m.uat_case_prefix == "UAT-"


def test_loads_sheet_specs(sample_manifest_path):
    m = Manifest.from_path(sample_manifest_path)
    assert m.req_sheet.name == "REQ"
    assert m.req_sheet.columns[0] == "Req ID"
    assert m.uat_sheet.name == "UAT Test Cases"
    assert m.uat_sheet.columns[3] == "User Journey ID"
    assert m.provenance_sheet_name == "Provenance"


def test_missing_scope_fails_loud(tmp_path):
    p = tmp_path / "oq.yaml"
    p.write_text("document:\n  title: t\n  project: p\n")
    with pytest.raises(ValueError) as exc:
        Manifest.from_path(p)
    assert "scope" in str(exc.value)


def test_scalar_columns_fails_loud(tmp_path):
    p = tmp_path / "oq.yaml"
    p.write_text(
        "document:\n  title: t\n  project: p\n"
        "scope: s\n"
        "sheets:\n  req:\n    name: R\n    columns: ID\n"
    )
    with pytest.raises(ValueError) as exc:
        Manifest.from_path(p)
    assert "columns" in str(exc.value)
