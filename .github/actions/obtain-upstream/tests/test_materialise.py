"""Offline tests for obtain.sh, run against a stub ``docker``.

This is the script both entry points run -- the composite action and any caller
obtaining several upstreams in a loop -- so testing it directly tests what
actually executes, with no extraction step to drift.

The stub records every call, which is how the no-op case is proved: not by the
exit code, which would be zero either way, but by the absence of a ``cp`` in
the record.

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

OBTAIN = pathlib.Path(__file__).resolve().parents[1] / "obtain.sh"

GOOD = "cbbbf10438edc6c2d83e8d0efbee4b32ced4feae"
OTHER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DIGEST = "ghcr.io/cure-hht/hht_diary@sha256:" + "b" * 64


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
        "GITHUB_ACTOR": "someone",
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "DOCKER_CALLS": str(calls),
    }
    proc = subprocess.run(
        [str(OBTAIN), "cure-hht/hht_diary", commit, str(dest),
         "unused-by-the-stub", "ghcr.io"],
        env=env, capture_output=True, text=True,
    )
    call_log = calls.read_text() if calls.exists() else ""
    return proc, dest, outputs.read_text(), call_log


def test_first_call_materialises_the_whole_tree(tmp_path):
    proc, dest, outputs, _ = _run(tmp_path, GOOD)
    assert proc.returncode == 0, proc.stderr
    assert (dest / "spec" / "a-requirement.md").is_file()
    assert (dest / ".hidden-file").is_file(), "dotfiles must travel; nothing curates a subset"
    assert (dest / ".upstream-digest").read_text().strip() == DIGEST


def test_second_call_for_the_same_commit_copies_nothing(tmp_path):
    _run(tmp_path, GOOD)
    proc, dest, outputs, calls = _run(tmp_path, GOOD)

    assert proc.returncode == 0, proc.stderr
    assert "already materialised" in proc.stdout
    assert " cp " not in f" {calls} ", f"a second copy was made: {calls!r}"
    assert "pull" not in calls, f"the registry was contacted again: {calls!r}"
    assert (dest / ".upstream-digest").read_text().strip() == DIGEST, \
        "the recorded digest survives a no-op"


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


def test_the_tree_records_which_repository_it_came_from(tmp_path):
    """An extracted tree is otherwise identified only by its directory name.

    The provenance record beside a compiled deliverable has to name `owner/repo`
    at a commit. `basename` of the destination yields neither, so the obtain
    step -- the only step that knows -- writes it down.
    """
    _, dest, _, _ = _run(tmp_path, GOOD)
    assert (dest / ".upstream-repo").read_text().strip() == "cure-hht/hht_diary"


def test_a_no_op_completes_an_identity_written_before_the_slug_existed(tmp_path):
    """A tree materialised by an older obtain holds content and half an identity.

    The no-op path returns early by design, so without this it is the one path
    that can leave a tree nothing downstream can name.
    """
    _, dest, _, _ = _run(tmp_path, GOOD)
    (dest / ".upstream-repo").unlink()

    proc, dest, _, calls = _run(tmp_path, GOOD)
    assert "already materialised" in proc.stdout
    assert " cp " not in f" {calls} ", "completing the stamp must not re-copy"
    assert (dest / ".upstream-repo").read_text().strip() == "cure-hht/hht_diary"
