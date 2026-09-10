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


def test_require_namespaces_defaults_to_empty(sample_manifest_path):
    """Optional by design: a manifest that declares nothing keeps the
    generator agnostic about who is federated."""
    assert Manifest.from_path(sample_manifest_path).require_namespaces == ()


def test_require_namespaces_loads(tmp_path, sample_manifest_dict):
    import yaml

    raw = dict(sample_manifest_dict)
    raw["require_namespaces"] = ["SPN", "PLT"]
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw))
    assert Manifest.from_path(path).require_namespaces == ("SPN", "PLT")


def test_scalar_require_namespaces_fails_loud(tmp_path, sample_manifest_dict):
    import yaml

    raw = dict(sample_manifest_dict)
    raw["require_namespaces"] = "SPN"
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError) as excinfo:
        Manifest.from_path(path)
    assert "require_namespaces" in str(excinfo.value)
