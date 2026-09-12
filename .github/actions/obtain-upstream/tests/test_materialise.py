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
- The token arrives in the environment. A command line is readable from /proc
  by every process on the runner, for as long as the call takes.
"""

from __future__ import annotations

import pathlib
import subprocess

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


def test_the_token_never_travels_as_an_argument(tmp_path):
    """docker login reads the token on stdin. Anything that put it in an argv
    would put it in /proc/<pid>/cmdline for every process on the runner."""
    proc, _, calls = _run(tmp_path, GOOD)
    assert proc.returncode == 0, proc.stderr
    assert "obtain.sh" in calls, \
        "the caller's argv was not recorded, so this test cannot discriminate"
    assert TOKEN not in calls, f"the token reached a command line: {calls!r}"


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
