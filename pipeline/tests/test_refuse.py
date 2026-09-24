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
    assert refuse.read_ledger(str(ledger)) == (
        None,
        [("install", "build"), ("guard", "build")],
    )


def test_the_repositorys_own_ledger_parses():
    """The shipped ledger must satisfy the reader that will judge it."""
    shipped = pathlib.Path(__file__).resolve().parents[1] / "phases.yaml"
    repo, ids = refuse.read_ledger(str(shipped))
    assert repo is None
    assert [name for name, _ in ids] == [
        "git-init",
        "install",
        "guard",
        "release-notes",
    ]
    # every phase in this repository's own ledger is due at the build gate
    assert {due for _, due in ids} == {"build"}


def test_diagnostics_go_to_stderr_and_stdout_stays_machine_readable(tmp_path, capsys):
    ledger = _write_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)
    _record(evidence, "guard", 3)

    _, captured = _run(capsys, ledger, evidence)

    json.loads(captured.out)  # stdout alone must still parse
    assert "REFUSE" in captured.err


# ---------------------------------------------------------------------------
# Namespacing. A consumer inherits its upstream's image, so one image carries
# both ledgers and both evidence trees. These are the cases where the two would
# otherwise collide -- which is the defect the design review named before any
# of this was built.
# ---------------------------------------------------------------------------


def _ledger_dir(tmp_path, **repos):
    d = tmp_path / "phases.d"
    d.mkdir(parents=True, exist_ok=True)
    for repo, phases in repos.items():
        body = f"repo: {repo}\nphases:\n" + "".join(f"  - id: {p}\n" for p in phases)
        (d / f"{repo}.yaml").write_text(body, encoding="utf-8")
    return d


def test_two_repositories_each_keep_their_own_evidence(tmp_path, capsys):
    """The platform and the sponsor both run a phase called 'requirements'."""
    ledgers = _ledger_dir(tmp_path, hht_diary=["requirements"], acme=["requirements"])
    root = tmp_path / "evidence"
    _record(root / "hht_diary", "requirements", 0)
    _record(root / "acme", "requirements", 0)

    code = refuse.main(["refuse", str(ledgers), str(root)])
    captured = capsys.readouterr()

    assert code == 0
    verdict = json.loads(captured.out)
    assert set(verdict["expected"]) == {"hht_diary/requirements", "acme/requirements"}


def test_an_upstream_phase_cannot_be_satisfied_by_the_consumers(tmp_path, capsys):
    """The exact collision: the sponsor passed, the platform never ran.

    If evidence were not namespaced, the sponsor's result would sit at the path
    the platform's would have used, and this would read as a pass.
    """
    ledgers = _ledger_dir(tmp_path, hht_diary=["requirements"], acme=["requirements"])
    root = tmp_path / "evidence"
    _record(root / "acme", "requirements", 0)
    # hht_diary recorded nothing at all.

    code = refuse.main(["refuse", str(ledgers), str(root)])
    captured = capsys.readouterr()

    assert code == 1
    verdict = json.loads(captured.out)
    assert verdict["refused"] == ["hht_diary/requirements"]
    assert "did not run" in verdict["phases"]["hht_diary/requirements"]["reason"]


def test_two_ledgers_claiming_one_repo_is_an_error(tmp_path, capsys):
    d = tmp_path / "phases.d"
    d.mkdir()
    (d / "a.yaml").write_text("repo: same\nphases:\n  - id: x\n", encoding="utf-8")
    (d / "b.yaml").write_text("repo: same\nphases:\n  - id: y\n", encoding="utf-8")
    (tmp_path / "evidence").mkdir()

    code = refuse.main(["refuse", str(d), str(tmp_path / "evidence")])

    assert code == 2


def test_a_ledger_declaring_repo_reads_it(tmp_path):
    ledger = tmp_path / "one.yaml"
    ledger.write_text("repo: hht_diary\nphases:\n  - id: build\n", encoding="utf-8")
    # no due_by line, so the gate is None -- which means due at every gate
    assert refuse.read_ledger(str(ledger)) == ("hht_diary", [("build", None)])


def test_two_ledgers_without_a_repo_are_refused(tmp_path, capsys):
    """Omitting `repo:` twice put both ledgers at the evidence root.

    The duplicate guard filtered `None` out before comparing, so this -- the
    version reachable by leaving a key out rather than by getting it wrong --
    slipped through, and the second ledger's phases were judged against the
    first's evidence.
    """
    d = tmp_path / "phases.d"
    d.mkdir()
    for name in ("one", "two"):
        (d / f"{name}.yaml").write_text("phases:\n  - id: install\n    due_by: build\n")

    evidence = tmp_path / "evidence"
    _record(evidence, "install", 0)

    assert _run(capsys, str(d), str(evidence))[0] == 2


# ---------------------------------------------------------------------------
# --gate. The ledger always carried due_by and this program always ignored it,
# so a phase due at qa was demanded at build and a sponsor image could not pass
# its own build gate.
# ---------------------------------------------------------------------------


def _gated_ledger(tmp_path):
    d = tmp_path / "phases.d"
    d.mkdir(exist_ok=True)
    (d / "sponsor.yaml").write_text(
        "repo: sponsor\n"
        "phases:\n"
        "  - id: compile\n    due_by: build\n"
        "  - id: browser\n    due_by: qa\n"
        "  - id: device\n    due_by: uat\n",
        encoding="utf-8",
    )
    return d


def test_due_by_is_read_off_the_ledger(tmp_path):
    d = _gated_ledger(tmp_path)
    repo, phases = refuse.read_ledger(str(d / "sponsor.yaml"))
    assert repo == "sponsor"
    assert phases == [("compile", "build"), ("browser", "qa"), ("device", "uat")]


def test_a_later_phase_is_deferred_at_the_build_gate(tmp_path, capsys):
    """The case that made the sponsor image unable to pass its own gate."""
    d = _gated_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence / "sponsor", "compile", 0)

    code = refuse.main(["refuse", "--gate", "build", str(d), str(evidence)])
    assert code == 0

    out = json.loads(capsys.readouterr().out)
    assert out["gate"] == "build"
    assert out["expected"] == ["sponsor/compile"]
    assert out["deferred"] == ["sponsor/browser (due by qa)", "sponsor/device (due by uat)"]


def test_the_same_phase_is_required_once_its_gate_arrives(tmp_path, capsys):
    d = _gated_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence / "sponsor", "compile", 0)

    assert refuse.main(["refuse", "--gate", "qa", str(d), str(evidence)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert "sponsor/browser" in out["refused"]
    assert out["deferred"] == ["sponsor/device (due by uat)"]


def test_without_a_gate_every_phase_is_still_required(tmp_path, capsys):
    """Backward compatibility: callers that pass nothing get the old question."""
    d = _gated_ledger(tmp_path)
    evidence = tmp_path / "evidence"
    _record(evidence / "sponsor", "compile", 0)

    assert refuse.main(["refuse", str(d), str(evidence)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["gate"] is None
    assert out["deferred"] == []
    assert set(out["refused"]) == {"sponsor/browser", "sponsor/device"}


def test_an_unknown_gate_is_refused_rather_than_guessed(tmp_path, capsys):
    d = _gated_ledger(tmp_path)
    assert refuse.main(["refuse", "--gate", "staging", str(d)]) == 2
    assert "is not a gate" in capsys.readouterr().err


def test_an_unknown_due_by_in_the_ledger_is_an_error(tmp_path):
    ledger = tmp_path / "bad.yaml"
    ledger.write_text(
        "phases:\n  - id: x\n    due_by: whenever\n", encoding="utf-8"
    )
    with pytest.raises(refuse.LedgerError, match="is not a gate"):
        refuse.read_ledger(str(ledger))


def test_a_gate_that_asks_about_nothing_is_not_a_pass(tmp_path, capsys):
    """Every declared phase deferred means this gate asked about nothing.

    read_ledger already refuses an empty ledger for exactly this reason. The
    gate filter reached the same hole from the other side: expected empty,
    refusals empty, exit 0 -- a vacuous pass on an image nobody checked.
    """
    d = tmp_path / "phases.d"
    d.mkdir()
    (d / "legs.yaml").write_text(
        "repo: legs\nphases:\n  - id: e2e\n    due_by: qa\n  - id: mob\n    due_by: uat\n",
        encoding="utf-8",
    )
    (tmp_path / "evidence").mkdir()

    assert refuse.main(["refuse", "--gate", "build", str(d), str(tmp_path / "evidence")]) == 2
    assert "nothing here to pass" in capsys.readouterr().err


def test_a_due_by_this_reader_cannot_parse_is_an_error(tmp_path):
    """Falling through to None would mean 'due at every gate', silently."""
    for body in ('    due_by: qa  # needs a deployed env\n', '    due_by: "qa"\n'):
        ledger = tmp_path / "bad.yaml"
        ledger.write_text("phases:\n  - id: b\n" + body, encoding="utf-8")
        with pytest.raises(refuse.LedgerError, match="bare gate name"):
            refuse.read_ledger(str(ledger))


def test_a_field_that_is_not_due_by_is_still_carried_quietly(tmp_path):
    """The stricter rule must not reject the fields it never cared about."""
    ledger = tmp_path / "ok.yaml"
    ledger.write_text(
        "phases:\n  - id: b\n    due_by: qa\n    description: anything at all # even this\n",
        encoding="utf-8",
    )
    assert refuse.read_ledger(str(ledger)) == (None, [("b", "qa")])
