"""Offline tests for obtain-associates.sh, run against a stub ``docker``.

This is the step that turns build-urs's pins into the associate roots the
compile federates. None of what it decides is observable from a green CI run:
the readiness fixture supplies paths, so on that route this script never runs,
and the first caller to supply pins is a consumer repository one merge away.

Four behaviours matter:

- Several pins each become a root, in the order given, at a destination that
  keeps the owner. A list that silently dropped an entry would compile a
  deliverable missing a whole repository's obligations and still report success.
- Pins together with a path input refuse. A run given both could compile from
  two revisions while reporting one; picking a winner is how that happens
  quietly.
- A malformed entry refuses before any registry call, naming the entry.
- The token never travels as a command-line argument, where every process on
  the runner can read it out of /proc.

The script is exercised through the real obtain.sh, so the contract between the
two -- argument order, and the token arriving in the environment -- is what the
test binds to, rather than a stub's idea of it.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

_HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[3] / "actions" / "obtain-upstream" / "tests"))

from stub_docker import DIGEST, write_payload, write_stub  # noqa: E402

OBTAIN_ASSOCIATES = _HERE.parents[1] / "obtain-associates.sh"

GOOD = "cbbbf10438edc6c2d83e8d0efbee4b32ced4feae"
OTHER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN = "a-token-no-argv-may-carry"


def _run(tmp_path: pathlib.Path, commits: str, *, path_root="", path_roots=""):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    payload = tmp_path / "payload"
    payload.mkdir(exist_ok=True)
    write_payload(payload)
    write_stub(bin_dir, payload)

    calls = tmp_path / "calls.log"
    calls.write_text("")
    outputs = tmp_path / "gh-output"
    outputs.write_text("")

    # `ps` reads every process on the box, so the recorded argv of the stub's
    # own invocations is where a token passed as an argument would show up.
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "GITHUB_ACTOR": "someone",
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "DOCKER_CALLS": str(calls),
        "GITHUB_OUTPUT": str(outputs),
        "COMMITS": commits,
        "TOKEN": TOKEN,
        "PATH_ROOT": path_root,
        "PATH_ROOTS": path_roots,
    }
    proc = subprocess.run(
        [str(OBTAIN_ASSOCIATES)], env=env, capture_output=True, text=True
    )
    return proc, outputs.read_text(), calls.read_text()


def _roots(outputs: str) -> list[str]:
    """The paths inside the step output's roots<<EOF ... EOF block."""
    lines = outputs.splitlines()
    start = lines.index("roots<<EOF")
    end = lines.index("EOF", start)
    return lines[start + 1 : end]


def test_each_pin_becomes_a_root_in_the_order_given(tmp_path):
    proc, outputs, _ = _run(
        tmp_path, f"cure-hht/hht_diary@{GOOD}\ncure-hht/hht_admin@{OTHER}\n"
    )
    assert proc.returncode == 0, proc.stderr

    roots = _roots(outputs)
    assert len(roots) == 2, f"a pin was dropped: {roots!r}"
    assert roots[0].endswith("/cure-hht/hht_diary")
    assert roots[1].endswith("/cure-hht/hht_admin")

    for root in roots:
        tree = pathlib.Path(root)
        assert (tree / "spec" / "a-requirement.md").is_file()
        assert (tree / ".upstream-digest").read_text().strip() == DIGEST


def test_the_owner_survives_in_the_destination(tmp_path):
    """Two owners may publish the same repository name; one tree must not
    land on the other's."""
    proc, outputs, _ = _run(
        tmp_path, f"cure-hht/hht_diary@{GOOD}\nanother-org/hht_diary@{OTHER}\n"
    )
    assert proc.returncode == 0, proc.stderr
    roots = _roots(outputs)
    assert len(set(roots)) == 2, f"two upstreams collided on one path: {roots!r}"


def test_two_pins_for_one_repository_refuse(tmp_path):
    """One repository cannot be at two commits in one compile. Obtaining both
    into one destination leaves the union of the two trees, stamped with
    whichever was second, and federates it twice."""
    proc, outputs, calls = _run(
        tmp_path, f"cure-hht/hht_diary@{GOOD}\ncure-hht/hht_diary@{OTHER}\n"
    )
    assert proc.returncode == 1
    assert "cure-hht/hht_diary" in proc.stdout + proc.stderr
    assert calls == "", "a contradiction must refuse before anything is obtained"
    assert "roots" not in outputs


def test_the_same_pin_twice_refuses(tmp_path):
    """Naming one repository twice at the same commit is still two entries for
    one root; the compile would federate that root twice."""
    proc, _, calls = _run(
        tmp_path, f"cure-hht/hht_diary@{GOOD}\ncure-hht/hht_diary@{GOOD}\n"
    )
    assert proc.returncode == 1
    assert calls == ""


def test_blank_lines_are_not_roots(tmp_path):
    proc, outputs, _ = _run(tmp_path, f"\n  \ncure-hht/hht_diary@{GOOD}\n\n")
    assert proc.returncode == 0, proc.stderr
    assert len(_roots(outputs)) == 1


def test_commits_naming_nothing_refuse(tmp_path):
    """Set but empty is not the same as unset: the caller believes it pinned,
    and a compile federating nothing would still report a deliverable."""
    proc, outputs, calls = _run(tmp_path, "\n   \n\n")
    assert proc.returncode == 1
    assert "names no repository" in proc.stdout
    assert calls == ""
    assert "roots" not in outputs


def test_pins_with_a_path_input_refuse(tmp_path):
    for kwargs in ({"path_root": "some/path"}, {"path_roots": "some/path"}):
        proc, outputs, calls = _run(
            tmp_path, f"cure-hht/hht_diary@{GOOD}\n", **kwargs
        )
        assert proc.returncode == 1, f"{kwargs} was accepted alongside pins"
        assert "could compile from two revisions" in proc.stdout
        assert calls == "", "a refusal must not reach the registry first"
        assert "roots" not in outputs


def test_a_malformed_entry_refuses_and_names_it(tmp_path):
    proc, _, calls = _run(tmp_path, "cure-hht/hht_diary\n")
    assert proc.returncode == 1
    assert "cure-hht/hht_diary" in proc.stdout
    assert "owner/repo@" in proc.stdout
    assert calls == "", "a malformed pin must refuse before contacting anything"


def test_a_name_without_an_owner_refuses(tmp_path):
    """The owner is what keeps two repositories of the same name apart. A pin
    that omits it reaches the collision by a route that looks like a pin."""
    proc, _, calls = _run(tmp_path, f"hht_diary@{GOOD}\n")
    assert proc.returncode == 1
    assert "owner/name" in proc.stdout + proc.stderr
    assert calls == ""


def test_an_entry_cannot_steer_the_destination_out_of_the_workspace(tmp_path):
    proc, _, calls = _run(tmp_path, f"../../../../tmp/pwned@{GOOD}\n")
    assert proc.returncode == 1
    assert "owner/name" in proc.stdout + proc.stderr
    assert calls == ""


def test_a_malformed_pin_refuses_before_anything_is_materialised(tmp_path):
    """A pin checked only where it resolves fails after earlier entries are
    already on disk, and reads as a registry problem rather than a typo."""
    proc, outputs, calls = _run(
        tmp_path, f"cure-hht/hht_diary@{GOOD}\ncure-hht/hht_admin@NOTAHEX\n"
    )
    assert proc.returncode == 1
    assert "40 hex characters" in proc.stdout + proc.stderr
    assert calls == "", "an entry was materialised before the list was checked"
    assert "roots" not in outputs

    runner_temp = tmp_path / "runner-temp"
    assert not runner_temp.exists() or not list(runner_temp.rglob(".upstream-commit"))


def test_an_uppercase_pin_refuses(tmp_path):
    proc, _, calls = _run(tmp_path, f"cure-hht/hht_diary@{GOOD.upper()}\n")
    assert proc.returncode == 1
    assert "lowercase" in proc.stdout + proc.stderr
    assert calls == ""


def test_a_missing_token_refuses(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    payload = tmp_path / "payload"
    payload.mkdir(exist_ok=True)
    write_payload(payload)
    write_stub(bin_dir, payload)
    proc = subprocess.run(
        [str(OBTAIN_ASSOCIATES)],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "RUNNER_TEMP": str(tmp_path / "runner-temp"),
            "DOCKER_CALLS": str(tmp_path / "calls.log"),
            "GITHUB_OUTPUT": str(tmp_path / "gh-output"),
            "COMMITS": f"cure-hht/hht_diary@{GOOD}\n",
            "TOKEN": "",
            "PATH_ROOT": "",
            "PATH_ROOTS": "",
        },
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "registry-token is required" in proc.stdout


def test_the_token_never_travels_as_an_argument(tmp_path):
    """docker login reads the token on stdin. Anything that put it in an argv
    would put it in /proc/<pid>/cmdline for every process on the runner."""
    proc, _, calls = _run(tmp_path, f"cure-hht/hht_diary@{GOOD}\n")
    assert proc.returncode == 0, proc.stderr
    assert "obtain.sh" in calls, \
        "the caller's argv was not recorded, so this test cannot discriminate"
    assert TOKEN not in calls, f"the token reached a command line: {calls!r}"
