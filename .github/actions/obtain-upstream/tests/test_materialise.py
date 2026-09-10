"""Offline tests for the obtain-upstream action's materialise step.

The step is extracted straight out of ``action.yml`` and run against a stub
``docker``, so the test cannot drift from the action the way a reimplementation
would. The stub records every call, which is how the no-op case is proved: not
by the exit code, which would be zero either way, but by the absence of a
``cp`` in the record.

Three behaviours matter here and none of them is observable from a green CI run
of the real thing:

- A first call materialises the tree and records what it holds.
- A second call naming the same commit copies nothing. A run that needs an
  upstream in five steps must obtain it once; two steps reading the same path
  must be reading the same bytes, not two copies that agree.
- A pin naming a commit that published no artifact refuses, and says why. It
  must not fall back to a nearby revision -- that is the silent substitution the
  whole arrangement exists to remove.
"""

from __future__ import annotations

import pathlib
import subprocess
import textwrap

import yaml

ACTION = pathlib.Path(__file__).resolve().parents[1] / "action.yml"
ACTION_DIR = ACTION.parent

GOOD = "cbbbf10438edc6c2d83e8d0efbee4b32ced4feae"
OTHER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DIGEST = "ghcr.io/cure-hht/hht_diary@sha256:" + "b" * 64


def _script() -> str:
    """The materialise step's shell, read out of the action itself."""
    doc = yaml.safe_load(ACTION.read_text())
    steps = doc["runs"]["steps"]
    step = next(s for s in steps if s.get("id") == "materialise")
    return step["run"]


def _stub_docker(bin_dir: pathlib.Path, payload: pathlib.Path, *, pull_ok: bool) -> None:
    """A docker that records its calls and needs no daemon."""
    pull_exit = "0" if pull_ok else "1"
    (bin_dir / "docker").write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo "$@" >> "$DOCKER_CALLS"
            case "$1" in
              login) exit 0 ;;
              pull) exit {pull_exit} ;;
              image) echo '{DIGEST}' ; exit 0 ;;
              create) echo 'stub-container-id' ; exit 0 ;;
              cp) cp -a '{payload}/.' "${{3}}" ; exit 0 ;;
              rm) exit 0 ;;
              *) echo "unexpected docker $1" >&2 ; exit 2 ;;
            esac
            """
        )
    )
    (bin_dir / "docker").chmod(0o755)


def _run(tmp_path: pathlib.Path, commit: str, *, pull_ok: bool = True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    payload = tmp_path / "payload"
    payload.mkdir(exist_ok=True)
    (payload / "spec").mkdir(exist_ok=True)
    (payload / "spec" / "a-requirement.md").write_text("# a requirement\n")
    (payload / ".hidden-file").write_text("dotfiles travel too\n")

    _stub_docker(bin_dir, payload, pull_ok=pull_ok)

    dest = tmp_path / "dest"

    # Reset both records per invocation. Two calls share a tmp_path on purpose
    # -- that is how the no-op case is set up -- so an accumulating log would
    # let the first call's `pull` and `cp` satisfy assertions about the second.
    calls = tmp_path / "calls.log"
    calls.write_text("")
    outputs = tmp_path / "gh-output"
    outputs.write_text("")

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "REPOSITORY": "cure-hht/hht_diary",
        "COMMIT": commit,
        "REGISTRY": "ghcr.io",
        "DEST_INPUT": str(dest),
        "TOKEN": "unused-by-the-stub",
        "ACTOR": "someone",
        "ACTION_PATH": str(ACTION_DIR),
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "GITHUB_OUTPUT": str(outputs),
        "DOCKER_CALLS": str(calls),
    }
    proc = subprocess.run(
        ["bash", "-c", _script()], env=env, capture_output=True, text=True
    )
    call_log = calls.read_text() if calls.exists() else ""
    return proc, dest, outputs.read_text(), call_log


def test_first_call_materialises_the_whole_tree(tmp_path):
    proc, dest, outputs, _ = _run(tmp_path, GOOD)
    assert proc.returncode == 0, proc.stderr
    assert (dest / "spec" / "a-requirement.md").is_file()
    assert (dest / ".hidden-file").is_file(), "dotfiles must travel; nothing curates a subset"
    assert f"path={dest}" in outputs
    assert f"digest={DIGEST}" in outputs


def test_second_call_for_the_same_commit_copies_nothing(tmp_path):
    _run(tmp_path, GOOD)
    proc, dest, outputs, calls = _run(tmp_path, GOOD)

    assert proc.returncode == 0, proc.stderr
    assert "already materialised" in proc.stdout
    assert " cp " not in f" {calls} ", f"a second copy was made: {calls!r}"
    assert "pull" not in calls, f"the registry was contacted again: {calls!r}"
    assert f"path={dest}" in outputs
    assert f"digest={DIGEST}" in outputs, "the recorded digest survives a no-op"


def test_a_different_commit_re_materialises(tmp_path):
    _run(tmp_path, GOOD)
    proc, _, _, calls = _run(tmp_path, OTHER)

    assert proc.returncode == 0, proc.stderr
    assert "pull" in calls, "a moved pin must fetch, not reuse the old tree"


def test_a_commit_that_published_nothing_refuses_and_says_why(tmp_path):
    proc, _, _, calls = _run(tmp_path, GOOD, pull_ok=False)

    assert proc.returncode == 1
    assert "no artifact published" in proc.stdout
    assert "one artifact per commit" in proc.stdout
    assert "will not fall back" in proc.stdout
    assert " cp " not in f" {calls} ", "a refusal must not leave a partial tree"
