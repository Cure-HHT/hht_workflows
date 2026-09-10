from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "compile-oq.py"


@pytest.fixture(scope="module")
def compile_oq():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("compile_oq", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_writes_all_three_outputs(
    compile_oq, tmp_path, sample_manifest_path, sample_trace_path, sample_graph_path
):
    counts = compile_oq.build(
        manifest_path=sample_manifest_path,
        trace_path=sample_trace_path,
        graph_path=sample_graph_path,
        out_csv_dir=tmp_path / "reports",
        out_xlsx=tmp_path / "build" / "oq.xlsx",
        provenance_overrides={"generated_at": "2026-09-09T12:00:00Z"},
    )
    assert counts == (3, 3)
    assert (tmp_path / "reports" / "oq-req.csv").exists()
    assert (tmp_path / "reports" / "oq-uat.csv").exists()
    assert (tmp_path / "build" / "oq.xlsx").exists()


def test_csv_outputs_are_reproducible(
    compile_oq, tmp_path, sample_manifest_path, sample_trace_path, sample_graph_path
):
    import hashlib

    digests = []
    for run in ("one", "two"):
        target = tmp_path / run
        compile_oq.build(
            manifest_path=sample_manifest_path,
            trace_path=sample_trace_path,
            graph_path=sample_graph_path,
            out_csv_dir=target,
            out_xlsx=target / "oq.xlsx",
            provenance_overrides={"generated_at": "2026-09-09T12:00:00Z"},
        )
        digests.append(
            (
                hashlib.sha256((target / "oq-req.csv").read_bytes()).hexdigest(),
                hashlib.sha256((target / "oq-uat.csv").read_bytes()).hexdigest(),
            )
        )
    assert digests[0] == digests[1]


def test_generated_at_override_reaches_the_workbook(
    compile_oq, tmp_path, sample_manifest_path, sample_trace_path, sample_graph_path
):
    """provenance_overrides is asserted as an input by every other test here;
    this asserts it as an effect. If build() silently ignored the override
    and stamped the real clock instead, every other test would still pass."""
    import openpyxl

    out_xlsx = tmp_path / "build" / "oq.xlsx"
    compile_oq.build(
        manifest_path=sample_manifest_path,
        trace_path=sample_trace_path,
        graph_path=sample_graph_path,
        out_csv_dir=tmp_path / "reports",
        out_xlsx=out_xlsx,
        provenance_overrides={"generated_at": "2026-09-09T12:00:00Z"},
    )
    manifest = compile_oq.Manifest.from_path(sample_manifest_path)
    wb = openpyxl.load_workbook(out_xlsx)
    prov_rows = dict(
        (row[0], row[1])
        for row in wb[manifest.provenance_sheet_name].iter_rows(values_only=True)
        if row and row[0]
    )
    assert prov_rows["Generated at (UTC)"] == "2026-09-09T12:00:00Z"


def test_main_prints_the_stdout_contract(
    compile_oq,
    tmp_path,
    monkeypatch,
    capsys,
    sample_manifest_path,
    sample_trace_path,
    sample_graph_path,
):
    """Task 7's composite action parses this exact printed line with `sed`
    to produce its two GitHub Actions outputs; a change to the format here
    would pass every other test in this file and break that step silently."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compile-oq.py",
            "--manifest",
            str(sample_manifest_path),
            "--trace",
            str(sample_trace_path),
            "--graph",
            str(sample_graph_path),
            "--out-csv-dir",
            str(tmp_path / "reports"),
            "--out-xlsx",
            str(tmp_path / "build" / "oq.xlsx"),
        ],
    )
    exit_code = compile_oq.main()
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "OQ report: 3 requirements, 3 UAT test cases\n"
