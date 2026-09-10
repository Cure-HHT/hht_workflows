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


def test_req_sheet_columns_are_loaded_in_order(sample_manifest_path):
    """Both verdict columns are declared by the consumer, in the order the
    rows emit them."""
    m = Manifest.from_path(sample_manifest_path)
    assert m.req_sheet.columns == (
        "Req ID",
        "Description",
        "Test Result",
        "UAT Result",
        "UAT Test Case ID",
    )


def test_req_sheet_with_the_older_single_verdict_header_is_refused(
    tmp_path, sample_manifest_dict
):
    """A consumer manifest still declaring one verdict column would be
    rendered with the journey column's title repeated over the UAT-result
    column, because the renderer repeats the last declared column to reach the
    widest row. A wrong header over real verdicts must be refused, not
    written."""
    import yaml

    raw = dict(sample_manifest_dict)
    raw["sheets"] = {
        **raw["sheets"],
        "req": {
            "name": "REQ",
            "columns": ["Req ID", "Description", "Pass/Fail", "UAT Test Case ID"],
        },
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError) as exc:
        Manifest.from_path(path)
    message = str(exc.value)
    assert "sheets.req" in message
    assert "5" in message
    assert "Pass/Fail" in message


def test_req_sheet_with_too_many_columns_is_refused(tmp_path, sample_manifest_dict):
    """Only one column repeats. A sixth declared column would silently become
    the repeating one and mislabel every journey column after the first."""
    import yaml

    raw = dict(sample_manifest_dict)
    raw["sheets"] = {
        **raw["sheets"],
        "req": {
            "name": "REQ",
            "columns": [
                "Req ID", "Description", "Test Result", "UAT Result",
                "UAT Test Case ID", "Extra",
            ],
        },
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError):
        Manifest.from_path(path)
