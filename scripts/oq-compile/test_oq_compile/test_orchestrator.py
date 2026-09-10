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
            hashlib.sha256((target / "oq-req.csv").read_bytes()).hexdigest()
        )
    assert digests[0] == digests[1]
