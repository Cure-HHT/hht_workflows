"""Tests for `pipeline/record`.

The wrapper's whole contract is: run the step, write down what happened, and
exit zero so the image survives a failure. The case worth testing hardest is the
one where the writing itself is impossible -- because the first version exited
zero anyway, reporting a status for a phase whose verdict reached no file. That
produced an image with no evidence and no signal, which is worse than a red
build, and it was found by running the thing rather than by reading it.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

RECORD = pathlib.Path(__file__).resolve().parents[1] / "record"


def run(evidence, *cmd):
    env = dict(os.environ, EVIDENCE_DIR=str(evidence))
    return subprocess.run(
        ["sh", str(RECORD), *cmd], env=env, capture_output=True, text=True
    )


def test_a_passing_step_is_recorded_and_exits_zero(tmp_path):
    ev = tmp_path / "evidence"
    result = run(ev, "ok-phase", "sh", "-c", "echo hello; exit 0")

    assert result.returncode == 0
    assert (ev / "ok-phase.rc").read_text().strip() == "0"
    assert "hello" in (ev / "ok-phase.log").read_text()


def test_a_failing_step_is_recorded_and_still_exits_zero(tmp_path):
    """The point of the wrapper: the build must survive so the image exists."""
    ev = tmp_path / "evidence"
    result = run(ev, "bad-phase", "sh", "-c", "echo boom >&2; exit 7")

    assert result.returncode == 0, "a failing step must not fail the build"
    assert (ev / "bad-phase.rc").read_text().strip() == "7"
    assert "boom" in (ev / "bad-phase.log").read_text()


def test_a_missing_command_is_distinguishable_from_a_failed_one(tmp_path):
    ev = tmp_path / "evidence"
    run(ev, "gone", "this-command-does-not-exist")

    assert (ev / "gone.rc").read_text().strip() == "127"


def test_an_unwritable_evidence_directory_FAILS(tmp_path):
    """The defect this test exists for.

    Exiting zero here would report a status that was never written down, and
    leave a published image carrying no record of the step at all.
    """
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        result = run(readonly / "evidence", "phase", "sh", "-c", "exit 0")
    finally:
        readonly.chmod(0o700)

    assert result.returncode != 0, "record must refuse to be silent about this"
    assert "cannot create the evidence directory" in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_an_existing_but_unwritable_directory_FAILS(tmp_path):
    ev = tmp_path / "evidence"
    ev.mkdir()
    ev.chmod(0o500)
    try:
        result = run(ev, "phase", "sh", "-c", "exit 0")
    finally:
        ev.chmod(0o700)

    assert result.returncode != 0
    assert "not writable" in result.stderr


def test_usage_error_is_reported(tmp_path):
    result = run(tmp_path / "evidence", "only-a-phase")
    assert result.returncode == 2
