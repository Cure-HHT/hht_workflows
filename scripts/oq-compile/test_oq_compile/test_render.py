from __future__ import annotations

import hashlib

import openpyxl

from oq_compile.manifest import Manifest
from oq_compile.render import Provenance, write_csv, write_workbook


def _provenance():
    return Provenance(
        primary_commit="abc1234",
        associate_commits=("def5678",),
        elspais_version="0.123.0",
        tool_version="v1.0.0",
        scope_name="example-scope",
        scope_lines=("Scope: level PRD or GUI",),
        generated_at="2026-09-09T12:00:00Z",
        req_count=3,
        uat_count=3,
    )


def test_csv_pads_rows_to_the_widest(tmp_path):
    out = tmp_path / "req.csv"
    write_csv(out, ("A", "B", "C"), [["1", "2", "3", "4", "5"], ["6", "7", "8"]])
    lines = out.read_text().splitlines()
    assert lines[0] == "A,B,C,C,C"
    assert lines[2] == "6,7,8,,"


def test_csv_is_byte_identical_across_runs(tmp_path):
    rows = [["1", "2", "3", "4"]]
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    write_csv(a, ("A", "B", "C"), rows)
    write_csv(b, ("A", "B", "C"), rows)
    assert hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(
        b.read_bytes()
    ).hexdigest()


def test_workbook_has_three_named_sheets(tmp_path, sample_manifest_path):
    m = Manifest.from_path(sample_manifest_path)
    out = tmp_path / "oq.xlsx"
    write_workbook(out, m, [["SPN-PRD-a", "A", "PASS", "JNY-1"]],
                   [["UAT-JNY-1", "J", "PASS", "JNY-1", "SPN-PRD-a"]], _provenance())
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["REQ", "UAT Test Cases", "Provenance"]


def test_workbook_writes_headers_and_rows(tmp_path, sample_manifest_path):
    m = Manifest.from_path(sample_manifest_path)
    out = tmp_path / "oq.xlsx"
    write_workbook(out, m, [["SPN-PRD-a", "A", "PASS", "JNY-1"]],
                   [["UAT-JNY-1", "J", "PASS", "JNY-1", "SPN-PRD-a"]], _provenance())
    ws = openpyxl.load_workbook(out)["REQ"]
    assert [c.value for c in ws[1]][:4] == [
        "Req ID", "Description", "Pass/Fail", "UAT Test Case ID",
    ]
    assert [c.value for c in ws[2]] == ["SPN-PRD-a", "A", "PASS", "JNY-1"]


def test_provenance_sheet_states_scope_and_timestamp(tmp_path, sample_manifest_path):
    m = Manifest.from_path(sample_manifest_path)
    out = tmp_path / "oq.xlsx"
    write_workbook(out, m, [], [], _provenance())
    ws = openpyxl.load_workbook(out)["Provenance"]
    text = "\n".join(
        str(c.value) for row in ws.iter_rows() for c in row if c.value is not None
    )
    assert "example-scope" in text
    assert "2026-09-09T12:00:00Z" in text
    assert "0.123.0" in text
    assert "NOT RUN" in text


def test_extra_columns_beyond_the_declared_header(tmp_path, sample_manifest_path):
    m = Manifest.from_path(sample_manifest_path)
    out = tmp_path / "oq.xlsx"
    write_workbook(out, m,
                   [["SPN-PRD-a", "A", "PASS", "JNY-1", "JNY-2", "JNY-3"]],
                   [], _provenance())
    ws = openpyxl.load_workbook(out)["REQ"]
    assert [c.value for c in ws[1]][:6] == [
        "Req ID", "Description", "Pass/Fail",
        "UAT Test Case ID", "UAT Test Case ID", "UAT Test Case ID",
    ]
