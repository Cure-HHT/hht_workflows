"""Tests for the guard that keeps a credential out of the workspace.

The guard exists because a step's output is defined as everything git reports
as untracked or ignored, so a credential sitting in the workspace is captured
and published by construction. The relocation that prevents it rests on an
implementation detail of a pinned third-party action -- which file the action
writes, and which variable decides where -- so the guard's job is to fail when
that detail changes rather than to agree that it has not.

Each case below is one way the arrangement can break, and every one of them is
green under a guard that merely checks the auth step exited zero.
"""

# Verifies: HHT-OPS-identity-over-keys/D
from __future__ import annotations

import pathlib
import subprocess

import pytest

GUARD = pathlib.Path(__file__).resolve().parents[1] / "no-credential-in-workspace.sh"


def run(workspace, creds_path=None):
    env = {"PATH": "/usr/bin:/bin", "GITHUB_WORKSPACE": str(workspace)}
    if creds_path is not None:
        env["GOOGLE_GHA_CREDS_PATH"] = str(creds_path)
    return subprocess.run(
        ["bash", str(GUARD)], env=env, capture_output=True, text=True
    )


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "README.md").write_text("a checkout\n")
    return ws


@pytest.fixture
def outside(tmp_path):
    d = tmp_path / "runner-temp" / "gcp-wif-auth"
    d.mkdir(parents=True)
    return d


def test_passes_when_the_credential_is_outside_the_workspace(workspace, outside):
    creds = outside / "gha-creds-deadbeef.json"
    creds.write_text("{}")
    result = run(workspace, creds)
    assert result.returncode == 0, result.stderr
    assert "outside the workspace" in result.stdout


def test_refuses_when_the_credential_is_inside_the_workspace(workspace):
    """The case the whole guard exists for: relocation stopped working."""
    creds = workspace / "gha-creds-deadbeef.json"
    creds.write_text("{}")
    result = run(workspace, creds)
    assert result.returncode == 1
    assert "inside the workspace" in result.stderr or "written into" in result.stderr


def test_refuses_a_stray_file_even_when_the_path_says_otherwise(workspace, outside):
    """A bump could write both, or write one and report the other.

    The guard must look at the workspace itself, not only believe the path the
    action reported. A check that trusted the report would pass here while a
    live credential sat in the tree about to be captured.
    """
    (workspace / "gha-creds-cafe1234.json").write_text("{}")
    result = run(workspace, outside / "gha-creds-deadbeef.json")
    assert result.returncode == 1
    assert "written into the workspace" in result.stderr


def test_refuses_when_no_credential_was_created_at_all(workspace):
    """Absence is a failure, not a pass.

    An unset path means the auth step produced nothing, and every consumer
    expecting application default credentials fails later, further from the
    cause. Treating this as success is how a guard passes while the thing it
    names does not work.
    """
    result = run(workspace, None)
    assert result.returncode == 1
    assert "no credentials file was created" in result.stderr


def test_two_stray_files_still_refuse_with_a_reason(workspace, outside):
    """More than one match still refuses cleanly, naming a reason.

    This does NOT prove the `-quit` in the script. The SIGPIPE it avoids needs
    the reader to exit while the writer still has output buffered, and two
    small files do not reliably produce that -- this case passes against the
    piped form as well. It is here because the multi-match path is worth
    covering at all, not as evidence for that change, which stands on reading
    the script rather than on a race this suite cannot stage deterministically.
    """
    (workspace / "gha-creds-aaaa1111.json").write_text("{}")
    (workspace / "gha-creds-bbbb2222.json").write_text("{}")
    result = run(workspace, outside / "gha-creds-deadbeef.json")
    assert result.returncode == 1, "expected a clean refusal, got %s" % result.returncode
    assert "written into the workspace" in result.stderr


def test_a_credential_in_a_subdirectory_is_caught_by_the_reported_path(workspace):
    """The scan looks at the workspace root, where this version writes.

    A version writing into a subdirectory instead is caught by the other
    check -- the reported path is under the workspace wherever it points --
    so the two together cover a relocation that moved rather than vanished.
    """
    nested = workspace / "nested" / "deeper"
    nested.mkdir(parents=True)
    creds = nested / "gha-creds-deadbeef.json"
    creds.write_text("{}")
    result = run(workspace, creds)
    assert result.returncode == 1
    assert "inside the workspace" in result.stderr


def test_a_sibling_directory_sharing_the_prefix_is_not_the_workspace(tmp_path):
    """`/w/workspace-2` must not count as being inside `/w/workspace`.

    A prefix comparison without the separator would refuse a correctly
    relocated credential, and a guard that cries wolf gets disabled.
    """
    ws = tmp_path / "workspace"
    ws.mkdir()
    sibling = tmp_path / "workspace-2"
    sibling.mkdir()
    creds = sibling / "gha-creds-deadbeef.json"
    creds.write_text("{}")
    result = run(ws, creds)
    assert result.returncode == 0, result.stderr
