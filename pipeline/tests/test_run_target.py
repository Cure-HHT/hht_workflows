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

RT = pathlib.Path(__file__).resolve().parents[1] / "run-target"


def _load():
    spec = importlib.util.spec_from_loader(
        "rt_under_test", importlib.machinery.SourceFileLoader("rt_under_test", str(RT))
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rt = _load()

DECL = """
[[scanning.test.targets]]
name = "pkg/one"
cwd = "pkg/one"
command = "sh -c 'mkdir -p coverage && echo x > coverage/machine.jsonl && echo y > coverage/lcov.info'"
results = "coverage/machine.jsonl"
coverage = "coverage/lcov.info"

[[scanning.test.targets]]
name = "pkg/silent"
cwd = "pkg/silent"
command = "true"
results = "coverage/machine.jsonl"
"""


def _repo(tmp_path):
    (tmp_path / ".elspais.toml").write_text(DECL, encoding="utf-8")
    (tmp_path / "pkg" / "one").mkdir(parents=True)
    (tmp_path / "pkg" / "silent").mkdir(parents=True)
    return tmp_path


def test_the_declared_targets_are_read(tmp_path):
    names = [t["name"] for t in rt.targets_in(str(_repo(tmp_path)))]
    assert names == ["pkg/one", "pkg/silent"]


def test_a_target_runs_its_declared_command_in_its_declared_directory(tmp_path):
    root = _repo(tmp_path)
    assert rt.main(["run-target", "pkg/one", str(root)]) == 0
    assert (root / "pkg" / "one" / "coverage" / "machine.jsonl").read_text().strip() == "x"


def test_a_target_that_produced_no_results_FAILS(tmp_path):
    """Green tests with no machine-readable output is the case that matters.

    The command succeeds. Without this check the phase records success and the
    report generator is handed nothing — which is how a log gets mistaken for a
    result.
    """
    root = _repo(tmp_path)
    assert rt.main(["run-target", "pkg/silent", str(root)]) == 1


def test_an_undeclared_target_is_refused(tmp_path):
    root = _repo(tmp_path)
    assert rt.main(["run-target", "pkg/nope", str(root)]) == 2


def test_a_missing_declaration_is_refused(tmp_path):
    assert rt.main(["run-target", "anything", str(tmp_path)]) == 2
