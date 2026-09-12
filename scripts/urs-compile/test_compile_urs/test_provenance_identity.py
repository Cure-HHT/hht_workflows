"""The provenance record names the source the deliverables were compiled from.

A deliverable that enumerates obligations is only as good as the claim that it
and the build it describes come from one revision. That claim lives in
``docs/<name>-build-provenance.md``, and until now both of its identity lookups
assumed a working git checkout.

An obtained artifact is not a checkout. ``obtain.sh`` extracts a tree from the
artifact its upstream published for a pinned commit; the tree has no ``.git``,
so ``git describe`` fails and the row reads ``unknown`` — precisely when the
source finally became pinned. The obtain step is the only place that knows both
facts without guessing, so it records them and the provenance record reads them.

These tests source ``source-identity.sh`` directly rather than extracting a
window out of ``compile-urs.sh``: it is the file both the compile and any later
caller run, so there is no extraction step to drift.
"""

from __future__ import annotations

import pathlib
import subprocess

HELPER = pathlib.Path(__file__).resolve().parents[1] / "source-identity.sh"

COMMIT = "015293a47d7c64c8fcacd8d94f8b87a3d88bc138"
SLUG = "cure-hht/hht_diary"


def _call(function: str, root: pathlib.Path) -> str:
    """Run one helper function against `root` and return what it printed."""
    script = f'. "{HELPER}"\n{function} "{root}"\n'
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _stamped(tmp_path: pathlib.Path) -> pathlib.Path:
    """A tree as `obtain.sh` leaves it: extracted content plus its stamps."""
    root = tmp_path / "obtained"
    root.mkdir()
    (root / ".upstream-commit").write_text(COMMIT + "\n")
    (root / ".upstream-repo").write_text(SLUG + "\n")
    return root


def _checkout(tmp_path: pathlib.Path) -> pathlib.Path:
    """A real git checkout with an origin remote and one tagged commit."""
    root = tmp_path / "checkout"
    root.mkdir()
    env = {
        "PATH": "/usr/bin:/bin",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    for args in (
        ["init", "-q", "-b", "main"],
        ["remote", "add", "origin", "https://github.com/cure-hht/hht_diary.git"],
        ["commit", "-q", "--allow-empty", "-m", "one"],
        ["tag", "v9.9.9"],
    ):
        subprocess.run(["git", "-C", str(root), *args], env=env, check=True)
    return root


def test_a_stamped_tree_reports_the_pinned_commit(tmp_path):
    assert _call("source_version", _stamped(tmp_path)) == COMMIT


def test_a_stamped_tree_reports_the_owner_and_repository(tmp_path):
    """`basename` would give `obtained`, naming a directory rather than a repo."""
    assert _call("source_slug", _stamped(tmp_path)) == SLUG


def test_a_checkout_still_reports_its_git_description(tmp_path):
    """The operator path stays until the sponsor cuts over."""
    root = _checkout(tmp_path)
    assert _call("source_version", root) == "v9.9.9"
    assert _call("source_slug", root) == "cure-hht/hht_diary"


def test_a_stamp_wins_over_a_git_description(tmp_path):
    """A stamped checkout is an obtained tree someone also ran `git init` in.

    The stamp names the commit the artifact was published for; the git
    description names whatever that working tree happens to hold. Only one of
    those is what the compile actually read.
    """
    root = _checkout(tmp_path)
    (root / ".upstream-commit").write_text(COMMIT + "\n")
    (root / ".upstream-repo").write_text(SLUG + "\n")
    assert _call("source_version", root) == COMMIT


def test_an_unidentifiable_tree_says_what_is_missing(tmp_path):
    """`unknown` is a word, not a finding.

    A provenance row reading `unknown` looks like a value and tells a reader
    nothing about which of the two identity sources was absent.
    """
    root = tmp_path / "bare"
    root.mkdir()
    for function in ("source_version", "source_slug"):
        reported = _call(function, root)
        assert "unknown" not in reported
        assert ".upstream-commit" in reported or "no git" in reported


def test_the_readiness_fixture_is_identifiable(tmp_path):
    """The end-to-end fixture proves the stamp path, so it has to carry one.

    Without this the readiness job compiles green while emitting a provenance
    record that names nothing — the exact failure this task exists to remove,
    passing its own check.
    """
    fixture = (
        pathlib.Path(__file__).resolve().parents[1]
        / "test_compile_urs"
        / "fixtures"
        / "readiness"
        / "associate"
    )
    assert (fixture / ".upstream-commit").is_file()
    assert "unknown" not in _call("source_version", fixture)


def _tool_identity(env: dict[str, str], root: pathlib.Path) -> tuple[str, str]:
    """What the record would name as the tool, under `env`."""
    script = (
        f'. "{HELPER}"\n'
        f'printf "%s\\t%s" "$(tool_slug "{root}")" "$(tool_version "{root}")"\n'
    )
    out = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": "/usr/bin:/bin", **env},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    slug, _, version = out.partition("\t")
    return slug.strip(), version.strip()


def test_the_tool_names_the_reference_that_invoked_it(tmp_path):
    """A remotely-`uses:`d action is a downloaded tarball with no `.git`.

    `git describe` against it fails, so without this the deliverable would name
    neither the source it read nor the tool that produced it. The two values
    below are exactly what a reviewer reads in the caller's `uses:` line.
    """
    env = {
        "GITHUB_ACTION_REPOSITORY": "Cure-HHT/hht_workflows",
        "GITHUB_ACTION_REF": "ec2de47775ad86d146b79c5f80f6bdda2e181064",
    }
    slug, version = _tool_identity(env, tmp_path)
    assert slug == "Cure-HHT/hht_workflows"
    assert version == "ec2de47775ad86d146b79c5f80f6bdda2e181064"


def test_the_invoking_reference_wins_over_a_git_description(tmp_path):
    """Locally, both answer. Only one of them is what the caller pinned."""
    root = _checkout(tmp_path)
    env = {
        "GITHUB_ACTION_REPOSITORY": "Cure-HHT/hht_workflows",
        "GITHUB_ACTION_REF": "ec2de47775ad86d146b79c5f80f6bdda2e181064",
    }
    _, version = _tool_identity(env, root)
    assert version == "ec2de47775ad86d146b79c5f80f6bdda2e181064"


def test_without_an_invoking_reference_the_tool_falls_back_to_git(tmp_path):
    """The operator runs the script from a checkout, with no action around it."""
    root = _checkout(tmp_path)
    slug, version = _tool_identity({}, root)
    assert slug == "cure-hht/hht_diary"  # the fixture checkout's origin
    assert version == "v9.9.9"


def test_the_action_passed_value_wins_over_the_runners(tmp_path):
    """The action names the two values under its own keys, not the runner's."""
    env = {
        "URS_TOOL_REPOSITORY": "Cure-HHT/hht_workflows",
        "URS_TOOL_REF": "4177c5d00000000000000000000000000000abcd",
        "GITHUB_ACTION_REPOSITORY": "someone/else",
        "GITHUB_ACTION_REF": "main",
    }
    slug, version = _tool_identity(env, tmp_path)
    assert slug == "Cure-HHT/hht_workflows"
    assert version == "4177c5d00000000000000000000000000000abcd"


def test_an_empty_action_context_does_not_blank_the_runners_value(tmp_path):
    """A locally-`uses:`d action supplies empty contexts.

    The action passes them through regardless, so an override would replace a
    value the runner had filled in correctly with nothing -- and the record
    would report the tool as unidentified while the runner knew exactly what it
    was running.
    """
    env = {
        "URS_TOOL_REPOSITORY": "",
        "URS_TOOL_REF": "",
        "GITHUB_ACTION_REPOSITORY": "Cure-HHT/hht_workflows",
        "GITHUB_ACTION_REF": "ec2de47775ad86d146b79c5f80f6bdda2e181064",
    }
    slug, version = _tool_identity(env, tmp_path)
    assert slug == "Cure-HHT/hht_workflows"
    assert version == "ec2de47775ad86d146b79c5f80f6bdda2e181064"
