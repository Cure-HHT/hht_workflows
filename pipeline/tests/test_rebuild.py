"""Tests for `pipeline/rebuild`.

The property that matters: a rebuild must not destroy the record it is checking
itself against. Everything else follows from that -- if the original evidence is
overwritten, there is nothing left to compare to and the rebuild can only ever
report success.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pathlib
import subprocess

RECORD = pathlib.Path(__file__).resolve().parents[1] / "record"
REBUILD_PATH = pathlib.Path(__file__).resolve().parents[1] / "rebuild"


def _load():
    spec = importlib.util.spec_from_loader(
        "rebuild_under_test",
        importlib.machinery.SourceFileLoader("rebuild_under_test", str(REBUILD_PATH)),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rebuild = _load()


def _record(evidence, phase, *cmd):
    env = dict(os.environ, EVIDENCE_DIR=str(evidence))
    subprocess.run(["sh", str(RECORD), phase, *cmd], env=env, capture_output=True)


def test_the_recorded_argv_round_trips_through_a_shell(tmp_path):
    """Quoting must survive, or a rebuild re-runs something else entirely."""
    ev = tmp_path / "evidence"
    _record(ev, "tricky", "sh", "-c", 'echo "a && b"; exit 0')

    assert rebuild.argv_for(str(ev), "tricky") == ["sh", "-c", 'echo "a && b"; exit 0']


def test_a_phase_with_no_command_is_not_re_runnable(tmp_path):
    """A joined leg has evidence but never ran here."""
    ev = tmp_path / "evidence"
    ev.mkdir(parents=True)
    (ev / "e2e.rc").write_text("0\n", encoding="utf-8")
    (ev / "e2e.log").write_text("from a leg\n", encoding="utf-8")

    assert rebuild.argv_for(str(ev), "e2e") is None


def test_the_original_status_is_read_not_guessed(tmp_path):
    ev = tmp_path / "evidence"
    _record(ev, "p", "sh", "-c", "exit 4")

    assert rebuild.original_status(str(ev), "p") == "4"
    assert rebuild.original_status(str(ev), "missing") == "absent"


def test_a_rebuild_writes_beside_the_original_and_leaves_it_alone(tmp_path):
    """The load-bearing property.

    If a rebuild overwrote the original verdict there would be nothing left to
    compare against, and it could only ever report success.
    """
    ev = tmp_path / "evidence"
    _record(ev, "p", "sh", "-c", "exit 0")
    original = (ev / "p.rc").read_text()

    # what a rebuild does: same phase, different evidence dir
    _record(ev / "rebuild", "p", "sh", "-c", "exit 9")

    assert (ev / "p.rc").read_text() == original, "the original verdict was overwritten"
    assert (ev / "rebuild" / "p.rc").read_text().strip() == "9"


# ---------------------------------------------------------------------------
# The fail-open paths. A green suite missed all of these: `rebuild.main()` was
# never called by any test, so the exit code -- the only thing CI reads -- had
# no coverage at all.
# ---------------------------------------------------------------------------


def _ledger(tmp_path, repo, *phases):
    d = tmp_path / "phases.d"
    d.mkdir(exist_ok=True)
    body = f"repo: {repo}\nphases:\n" + "".join(
        f"  - id: {p}\n    due_by: build\n" for p in phases
    )
    (d / f"{repo}.yaml").write_text(body)
    return d


def test_reproducing_nothing_is_not_success(tmp_path, monkeypatch):
    """Every phase skipped used to exit 0 -- rule 4 passing on no evidence."""
    ledgers = _ledger(tmp_path, "solo", "alpha", "beta")
    ev = tmp_path / "evidence" / "solo"
    ev.mkdir(parents=True)
    for phase in ("alpha", "beta"):
        # a joined leg: a verdict and a log, but no command to re-run
        (ev / f"{phase}.rc").write_text("0\n")
        (ev / f"{phase}.log").write_text("came from elsewhere\n")

    monkeypatch.setenv("EVIDENCE_ROOT", str(tmp_path / "evidence"))
    monkeypatch.setenv("PIPELINE_LEDGER_DIR", str(ledgers))
    assert rebuild.main(["rebuild"]) == 1


def test_an_absent_verdict_is_not_an_agreement(tmp_path, monkeypatch):
    """`absent == absent` compared two strings and called it reproduced."""
    ledgers = _ledger(tmp_path, "solo", "alpha")
    ev = tmp_path / "evidence" / "solo"
    ev.mkdir(parents=True)
    # a command to re-run, but no recorded verdict to compare against
    (ev / "alpha.cmd").write_bytes(b"sh\x00-c\x00true\x00")
    (ev / "alpha.cwd").write_text(str(tmp_path))

    monkeypatch.setenv("EVIDENCE_ROOT", str(tmp_path / "evidence"))
    monkeypatch.setenv("PIPELINE_LEDGER_DIR", str(ledgers))
    monkeypatch.setattr(rebuild, "RECORD", str(RECORD))
    assert rebuild.main(["rebuild"]) == 1


def test_a_phase_that_reproduces_still_passes(tmp_path, monkeypatch):
    """The fixes must not make a genuine rebuild fail."""
    ledgers = _ledger(tmp_path, "solo", "alpha")
    ev = tmp_path / "evidence" / "solo"
    ev.mkdir(parents=True)
    _record(ev, "alpha", "sh", "-c", "exit 0")

    monkeypatch.setenv("EVIDENCE_ROOT", str(tmp_path / "evidence"))
    monkeypatch.setenv("PIPELINE_LEDGER_DIR", str(ledgers))
    monkeypatch.setattr(rebuild, "RECORD", str(RECORD))
    assert rebuild.main(["rebuild"]) == 0


def test_a_reproduced_failure_is_not_a_pass(tmp_path, monkeypatch):
    """`docker run <image>` must not report success on a failed phase.

    rebuild is the default command of these images. A phase that failed and
    fails again identically is deterministic, which is a true answer to the
    wrong question -- the caller is asking whether the image is sound. Exiting
    0 here would let a toolchain refusal reach CI as a green run.
    """
    ledgers = _ledger(tmp_path, "solo", "alpha")
    ev = tmp_path / "evidence" / "solo"
    ev.mkdir(parents=True)
    _record(ev, "alpha", "sh", "-c", "exit 7")
    assert (ev / "alpha.rc").read_text().strip() == "7"

    monkeypatch.setenv("EVIDENCE_ROOT", str(tmp_path / "evidence"))
    monkeypatch.setenv("PIPELINE_LEDGER_DIR", str(ledgers))
    monkeypatch.setattr(rebuild, "RECORD", str(RECORD))
    assert rebuild.main(["rebuild"]) == 1
