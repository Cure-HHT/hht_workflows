"""Tests for `pipeline/run-target`.

The point of this program is that the pipeline runs what the repository
DECLARES, so a hard-coded command cannot drift from it. The tests therefore care
about two things: that the declaration is obeyed, and that a target which
produced no machine-readable results is reported as a failure rather than as a
pass — because a green run with no results file is a phase the traceability
report cannot use, and nothing else would notice.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib

import pytest

RT = pathlib.Path(__file__).resolve().parents[1] / "run-target"


def _load():
    spec = importlib.util.spec_from_loader(
        "rt_under_test", importlib.machinery.SourceFileLoader("rt_under_test", str(RT))
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rt = _load()

# A stand-in for `elspais fingerprint`, keeping its contract: `start` empties
# <root>/.results/<name> and prints it, `finish` writes the fingerprint and is
# refused when no `start` began.
FAKE_ELSPAIS = """#!/bin/sh
set -eu
[ "$1" = fingerprint ] || exit 64
dir="$PWD/.results/$3"
case "$2" in
  start) rm -rf "$dir"; mkdir -p "$dir"; : > "$dir/.started"; echo "$dir" ;;
  finish) [ -f "$dir/.started" ] || { echo "no run began" >&2; exit 1; }
          rm "$dir/.started"; echo '{}' > "$dir/.elspais-run.json" ;;
  *) exit 64 ;;
esac
"""


@pytest.fixture(autouse=True)
def fake_elspais(tmp_path_factory, monkeypatch):
    bindir = tmp_path_factory.mktemp("bin")
    exe = bindir / "elspais"
    exe.write_text(FAKE_ELSPAIS, encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("ELSPAIS", str(exe))
    return exe

DECL = """
[[scanning.test.targets]]
name = "pkg-one"
cwd = "pkg/one"
command = "sh -c 'pwd > \\"$ELSPAIS_TARGET_OUTPUT/ran-in\\" && echo x > \\"$ELSPAIS_TARGET_OUTPUT/machine.jsonl\\" && echo y > \\"$ELSPAIS_TARGET_OUTPUT/lcov.info\\"'"
results = "machine.jsonl"
coverage = "lcov.info"

[[scanning.test.targets]]
name = "pkg-silent"
cwd = "pkg/silent"
command = "true"
results = "machine.jsonl"
"""


def _repo(tmp_path):
    (tmp_path / ".elspais.toml").write_text(DECL, encoding="utf-8")
    (tmp_path / "pkg" / "one").mkdir(parents=True)
    (tmp_path / "pkg" / "silent").mkdir(parents=True)
    return tmp_path


def test_the_declared_targets_are_read(tmp_path):
    names = [t["name"] for t in rt.targets_in(str(_repo(tmp_path)))]
    assert names == ["pkg-one", "pkg-silent"]


def test_a_target_runs_its_declared_command_in_its_declared_directory(tmp_path):
    root = _repo(tmp_path)
    assert rt.main(["run-target", "pkg-one", str(root)]) == 0
    folder = root / ".results" / "pkg-one"
    assert (folder / "ran-in").read_text().strip() == str(root / "pkg" / "one")
    assert (folder / "machine.jsonl").read_text().strip() == "x"


def test_a_run_records_its_fingerprint(tmp_path):
    """Results without a fingerprint read as stale, so the run must finish one."""
    root = _repo(tmp_path)
    assert rt.main(["run-target", "pkg-one", str(root)]) == 0
    assert (root / ".results" / "pkg-one" / ".elspais-run.json").is_file()


def test_a_failed_fingerprint_start_is_not_a_test_failure(tmp_path, monkeypatch, capsys):
    """No record could begin, so the tests never ran: status 2, not 1."""
    root = _repo(tmp_path)
    monkeypatch.setenv("ELSPAIS", "false")
    assert rt.main(["run-target", "pkg-one", str(root)]) == 2
    assert "fingerprint start" in capsys.readouterr().err


def test_a_target_that_produced_no_results_FAILS(tmp_path):
    """Green tests with no machine-readable output is the case that matters.

    The command succeeds. Without this check the phase records success and the
    report generator is handed nothing — which is how a log gets mistaken for a
    result.
    """
    root = _repo(tmp_path)
    assert rt.main(["run-target", "pkg-silent", str(root)]) == 1


def test_an_undeclared_target_is_refused(tmp_path):
    root = _repo(tmp_path)
    assert rt.main(["run-target", "pkg-nope", str(root)]) == 2


def test_a_missing_declaration_is_refused(tmp_path):
    assert rt.main(["run-target", "anything", str(tmp_path)]) == 2


def _toml(tmp_path, body):
    (tmp_path / ".elspais.toml").write_text(body)
    return tmp_path


def test_a_list_command_is_refused_rather_than_hanging(tmp_path, capsys):
    """`shell=True` with a list runs a bare `sh`, which blocks on stdin.

    Under `record` inside a build that consumes the whole job timeout with
    nothing said, so the declaration is rejected by name instead.
    """
    root = _toml(tmp_path, '''
[[scanning.test.targets]]
name = "t"
cwd = "."
command = ["sh", "-c", "true"]
''')
    assert rt.main(["run-target", "t", str(root)]) == 2
    assert "must be a string" in capsys.readouterr().err


def test_a_malformed_declaration_is_a_declaration_error(tmp_path, capsys):
    """Exit 1 here reaches refuse as 'failed with status 1' -- a test failure."""
    root = _toml(tmp_path, "[[scanning.test.targets]\nname = broken")
    assert rt.main(["run-target", "t", str(root)]) == 2
    assert "cannot parse" in capsys.readouterr().err


def test_a_leftover_results_file_does_not_satisfy_the_check(tmp_path, capsys):
    """A rerun in a dirty workspace is the case this check exists to catch."""
    root = _toml(tmp_path, '''
[[scanning.test.targets]]
name = "t"
cwd = "."
command = "true"
results = "r.json"
''')
    (root / ".results" / "t").mkdir(parents=True)
    (root / ".results" / "t" / "r.json").write_text('{"stale": true}')
    assert rt.main(["run-target", "t", str(root)]) == 1
    assert "MISSING" in capsys.readouterr().err


def test_a_cwd_that_does_not_exist_is_a_declaration_error(tmp_path, capsys):
    root = _toml(tmp_path, '''
[[scanning.test.targets]]
name = "t"
cwd = "nowhere"
command = "true"
''')
    assert rt.main(["run-target", "t", str(root)]) == 2


def test_a_results_glob_is_matched_as_elspais_reads_it(tmp_path):
    root = _toml(tmp_path, '''
[[scanning.test.targets]]
name = "t"
cwd = "."
command = "sh -c 'mkdir -p \\"$ELSPAIS_TARGET_OUTPUT/pixel\\" && echo x > \\"$ELSPAIS_TARGET_OUTPUT/pixel/journey-results.xml\\"'"
results = "*/journey-results.xml"
''')
    assert rt.main(["run-target", "t", str(root)]) == 0


def test_a_command_that_cannot_run_keeps_its_own_status(tmp_path):
    """127 says the command was not found; reporting the missing results as 1
    would hide that the tests never started."""
    root = _toml(tmp_path, '''
[[scanning.test.targets]]
name = "t"
cwd = "."
command = "no-such-runner-xyz"
results = "r.json"
''')
    assert rt.main(["run-target", "t", str(root)]) == 127


def test_a_start_that_names_no_folder_is_not_a_test_failure(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    monkeypatch.setenv("ELSPAIS", "true")
    assert rt.main(["run-target", "pkg-one", str(root)]) == 2
    assert "named no folder" in capsys.readouterr().err
