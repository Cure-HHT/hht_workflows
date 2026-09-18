"""Tests for `pipeline/refuse`.

The load-bearing case is `test_absent_verdict_is_a_refusal`. Treating a missing
result as a pass is how a gate reports success for work that never happened, and
it is the failure mode this repository has already shipped once.

`refuse` has no .py suffix -- it is a program the image carries at a fixed path,
not a module anything imports in production -- so the tests load it by path.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import pathlib
import sys

import pytest

REFUSE_PATH = pathlib.Path(__file__).resolve().parents[1] / "refuse"


def _load():
    spec = importlib.util.spec_from_loader(
        "refuse_under_test",
        importlib.machinery.SourceFileLoader("refuse_under_test", str(REFUSE_PATH)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


refuse = _load()


LEDGER = """\
phases:
  - id: install
    due_by: build
    description: The install.
  - id: guard
    due_by: build
"""


def _write_ledger(tmp_path, text=LEDGER):
    path = tmp_path / "phases.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _record(evidence, phase, status, log=True):
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"{phase}.rc").write_text(f"{status}\n", encoding="utf-8")
    if log:
        (evidence / f"{phase}.log").write_text("output\n", encoding="utf-8")


def _run(capsys, ledger, evidence):
    code = refuse.main(["refuse", str(ledger), str(evidence)])
    captured = capsys.readouterr()
    return code, captured


def test_every_phase_passed(tmp_path, capsys):
    ledger = _write_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)
    _record(evidence, "guard", 0)

    code, captured = _run(capsys, ledger, evidence)

    assert code == 0
    verdict = json.loads(captured.out)
    assert verdict["passed"] is True
    assert verdict["refused"] == []


def test_absent_verdict_is_a_refusal(tmp_path, capsys):
    """A phase that recorded nothing did not run, and must not read as a pass."""
    ledger = _write_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)
    # 'guard' records nothing at all.

    code, captured = _run(capsys, ledger, evidence)

    assert code == 1
    verdict = json.loads(captured.out)
    assert verdict["refused"] == ["guard"]
    assert "did not run" in verdict["phases"]["guard"]["reason"]


def test_failed_phase_is_refused_and_names_its_status(tmp_path, capsys):
    ledger = _write_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)
    _record(evidence, "guard", 1)

    code, captured = _run(capsys, ledger, evidence)

    assert code == 1
    verdict = json.loads(captured.out)
    assert verdict["phases"]["guard"]["reason"] == "failed with status 1"


def test_missing_tool_is_distinguishable_from_a_failed_check(tmp_path, capsys):
    """127 and 1 must not collapse into 'it did not pass'."""
    ledger = _write_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)
    _record(evidence, "guard", 127)

    _, captured = _run(capsys, ledger, evidence)

    assert "127" in json.loads(captured.out)["phases"]["guard"]["reason"]


def test_status_without_a_log_is_a_refusal(tmp_path, capsys):
    """The wrapper writes the log first, so a lone status came from elsewhere."""
    ledger = _write_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)
    _record(evidence, "guard", 0, log=False)

    code, captured = _run(capsys, ledger, evidence)

    assert code == 1
    assert "without a log" in json.loads(captured.out)["phases"]["guard"]["reason"]


def test_unreadable_status_is_a_refusal(tmp_path, capsys):
    ledger = _write_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)
    (evidence / "guard.rc").write_text("passed\n", encoding="utf-8")
    (evidence / "guard.log").write_text("output\n", encoding="utf-8")

    code, captured = _run(capsys, ledger, evidence)

    assert code == 1
    assert "not a status" in json.loads(captured.out)["phases"]["guard"]["reason"]


def test_no_evidence_directory_at_all(tmp_path, capsys):
    ledger = _write_ledger(tmp_path)

    code, _ = _run(capsys, ledger, tmp_path / "nowhere")

    assert code == 2


def test_empty_ledger_does_not_pass_vacuously(tmp_path, capsys):
    ledger = _write_ledger(tmp_path, "phases:\n")
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    code, _ = _run(capsys, ledger, evidence)

    assert code == 2


def test_unrecognised_ledger_line_is_an_error_not_a_guess(tmp_path, capsys):
    ledger = _write_ledger(tmp_path, "phases:\n  - name: install\n")
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    code, _ = _run(capsys, ledger, evidence)

    assert code == 2


def test_duplicate_phase_is_an_error(tmp_path, capsys):
    text = "phases:\n  - id: install\n  - id: install\n"
    ledger = _write_ledger(tmp_path, text)
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    code, _ = _run(capsys, ledger, evidence)

    assert code == 2


def test_ledger_ids_are_read_in_order(tmp_path):
    ledger = _write_ledger(tmp_path)
    assert refuse.read_ledger(str(ledger)) == ["install", "guard"]


def test_the_repositorys_own_ledger_parses():
    """The shipped ledger must satisfy the reader that will judge it."""
    shipped = pathlib.Path(__file__).resolve().parents[1] / "phases.yaml"
    ids = refuse.read_ledger(str(shipped))
    assert ids == ["git-init", "install", "guard", "release-notes"]


def test_diagnostics_go_to_stderr_and_stdout_stays_machine_readable(tmp_path, capsys):
    ledger = _write_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)
    _record(evidence, "guard", 3)

    _, captured = _run(capsys, ledger, evidence)

    json.loads(captured.out)  # stdout alone must still parse
    assert "REFUSE" in captured.err
