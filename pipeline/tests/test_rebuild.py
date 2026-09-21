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
