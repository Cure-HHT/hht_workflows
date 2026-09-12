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
import sys

import pytest

from stub_docker import DIGEST, write_payload, write_stub

OBTAIN = pathlib.Path(__file__).resolve().parents[1] / "obtain.sh"

GOOD = "cbbbf10438edc6c2d83e8d0efbee4b32ced4feae"
OTHER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN = "a-token-no-argv-may-carry"


def _ran(calls: str, subcommand: str) -> bool:
    """Whether the stub was asked to run `docker <subcommand>`.

    Matched as the first word of a recorded line. A substring test cannot
    distinguish the command from a path that contains it, and one written as
    `" cp "` never matches at all, because the subcommand opens the line.
    """
    return any(
        line.split(" ")[0] == subcommand for line in calls.splitlines() if line
    )


def _run(tmp_path: pathlib.Path, commit: str, *, pull_ok: bool = True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    payload = tmp_path / "payload"
    payload.mkdir(exist_ok=True)
    write_payload(payload)

    write_stub(bin_dir, payload, pull_ok=pull_ok)

    dest = tmp_path / "dest"

    # Reset the record per invocation. Two calls share a tmp_path on purpose
    # -- that is how the no-op case is set up -- so an accumulating log would
    # let the first call's `pull` and `cp` satisfy assertions about the second.
    calls = tmp_path / "calls.log"
    calls.write_text("")

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "GITHUB_ACTOR": "someone",
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "DOCKER_CALLS": str(calls),
        "TOKEN": TOKEN,
    }
    proc = subprocess.run(
        [str(OBTAIN), "cure-hht/hht_diary", commit, str(dest), "ghcr.io"],
        env=env, capture_output=True, text=True,
    )
    call_log = calls.read_text() if calls.exists() else ""
    return proc, dest, call_log


def test_first_call_materialises_the_whole_tree(tmp_path):
    proc, dest, _ = _run(tmp_path, GOOD)
    assert proc.returncode == 0, proc.stderr
    assert (dest / "spec" / "a-requirement.md").is_file()
    assert (dest / ".hidden-file").is_file(), "dotfiles must travel; nothing curates a subset"
    assert (dest / ".upstream-digest").read_text().strip() == DIGEST


def test_second_call_for_the_same_commit_copies_nothing(tmp_path):
    _run(tmp_path, GOOD)
    proc, dest, calls = _run(tmp_path, GOOD)

    assert proc.returncode == 0, proc.stderr
    assert "already materialised" in proc.stdout
    assert not _ran(calls, "cp"), f"a second copy was made: {calls!r}"
    assert "pull" not in calls, f"the registry was contacted again: {calls!r}"
    assert (dest / ".upstream-digest").read_text().strip() == DIGEST, \
        "the recorded digest survives a no-op"


def test_a_different_commit_re_materialises(tmp_path):
    _run(tmp_path, GOOD)
    proc, _, calls = _run(tmp_path, OTHER)

    assert proc.returncode == 0, proc.stderr
    assert "pull" in calls, "a moved pin must fetch, not reuse the old tree"


def test_a_file_deleted_upstream_does_not_survive_a_moved_pin(tmp_path):
    """The tree must be what the pin holds, not the union of every pin it has
    held. A file that outlives its deletion is a requirement the deliverable
    enumerates and the commit it names does not contain."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dest = tmp_path / "dest"
    calls = tmp_path / "calls.log"
    calls.write_text("")
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "GITHUB_ACTOR": "someone",
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "DOCKER_CALLS": str(calls),
        "TOKEN": TOKEN,
    }

    def obtain(commit: str, payload: pathlib.Path):
        write_stub(bin_dir, payload)
        return subprocess.run(
            [str(OBTAIN), "cure-hht/hht_diary", commit, str(dest)],
            env=env, capture_output=True, text=True,
        )

    at_good = tmp_path / "at-good"
    (at_good / "spec").mkdir(parents=True)
    (at_good / "spec" / "withdrawn.md").write_text("withdrawn before OTHER\n")
    assert obtain(GOOD, at_good).returncode == 0

    at_other = tmp_path / "at-other"
    (at_other / "spec").mkdir(parents=True)
    (at_other / "spec" / "current.md").write_text("the only requirement\n")
    proc = obtain(OTHER, at_other)

    assert proc.returncode == 0, proc.stderr
    assert (dest / "spec" / "current.md").is_file()
    assert not (dest / "spec" / "withdrawn.md").exists(), \
        "a file deleted upstream survived; the tree is the union of two pins"
    assert (dest / ".upstream-commit").read_text().strip() == OTHER


def test_a_commit_that_published_nothing_refuses_and_says_why(tmp_path):
    proc, _, calls = _run(tmp_path, GOOD, pull_ok=False)

    assert proc.returncode == 1
    assert "no artifact published" in proc.stdout
    assert "one artifact per commit" in proc.stdout
    assert "will not fall back" in proc.stdout
    assert not _ran(calls, "cp"), "a refusal must not leave a partial tree"


def test_a_missing_token_refuses_before_the_registry(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    payload = tmp_path / "payload"
    payload.mkdir(exist_ok=True)
    write_payload(payload)
    write_stub(bin_dir, payload)
    calls = tmp_path / "calls.log"
    calls.write_text("")

    proc = subprocess.run(
        [str(OBTAIN), "cure-hht/hht_diary", GOOD, str(tmp_path / "dest")],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "RUNNER_TEMP": str(tmp_path / "runner-temp"),
            "DOCKER_CALLS": str(calls),
        },
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "TOKEN must be set in the environment" in proc.stdout
    assert calls.read_text() == "", "a refusal must not reach the registry"


def test_the_default_destination_keeps_the_owner(tmp_path):
    """Two owners may publish the same repository name; the destination must
    separate them, and both entry points must derive it the same way."""
    proc = subprocess.run(
        [str(OBTAIN), "--dest-for", "cure-hht/hht_diary", GOOD],
        env={"PATH": "/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"{tmp_path}/upstream/cure-hht/hht_diary"


def test_an_uppercase_repository_refuses_rather_than_failing_at_the_registry(tmp_path):
    """A registry reference is lowercase. An uppercase owner passes every check
    that reads it as text, then dies at `docker pull` reported as an artifact
    the upstream never published -- which sends the reader to the wrong place."""
    proc = subprocess.run(
        [str(OBTAIN), "--dest-for", "Cure-HHT/hht_diary", GOOD],
        env={"PATH": "/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
        capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "lowercase" in proc.stdout + proc.stderr
    assert proc.stdout.strip() == "", "a refusal must not also print a path"


def test_the_destination_is_not_answered_for_a_pin_that_cannot_resolve(tmp_path):
    """A caller asking where a pin lands is asking about a pin. Answering for
    one that names no artifact would hand back a path to fill from nothing."""
    for bad in ("NOTAHEX", GOOD.upper(), ""):
        proc = subprocess.run(
            [str(OBTAIN), "--dest-for", "cure-hht/hht_diary", bad],
            env={"PATH": "/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0, f"{bad!r} was answered for"
        assert proc.stdout.strip() == "", "a refusal must not also print a path"


def test_the_tree_records_which_repository_it_came_from(tmp_path):
    """An extracted tree is otherwise identified only by its directory name.

    The provenance record beside a compiled deliverable has to name `owner/repo`
    at a commit. `basename` of the destination yields neither, so the obtain
    step -- the only step that knows -- writes it down.
    """
    _, dest, _ = _run(tmp_path, GOOD)
    assert (dest / ".upstream-repo").read_text().strip() == "cure-hht/hht_diary"


def test_a_no_op_completes_an_identity_written_before_the_slug_existed(tmp_path):
    """A tree materialised by an older obtain holds content and half an identity.

    The no-op path returns early by design, so without this it is the one path
    that can leave a tree nothing downstream can name.
    """
    _, dest, _ = _run(tmp_path, GOOD)
    (dest / ".upstream-repo").unlink()

    proc, dest, calls = _run(tmp_path, GOOD)
    assert "already materialised" in proc.stdout
    assert not _ran(calls, "cp"), "completing the stamp must not re-copy"
    assert (dest / ".upstream-repo").read_text().strip() == "cure-hht/hht_diary"


def test_the_identity_survives_a_moved_pin(tmp_path):
    """The swap replaces the tree wholesale, so the identity has to be written
    into the staged tree rather than into the destination it replaces."""
    _run(tmp_path, GOOD)
    _, dest, _ = _run(tmp_path, OTHER)
    assert (dest / ".upstream-repo").read_text().strip() == "cure-hht/hht_diary"
