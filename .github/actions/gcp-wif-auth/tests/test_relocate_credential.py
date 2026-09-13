"""Tests for moving the credentials file out of the workspace.

google-github-actions/auth writes the file into $GITHUB_WORKSPACE and offers no
input to move it. This script moves it afterwards, which depends on nothing but
the filesystem -- unlike overriding GITHUB_WORKSPACE for the auth step, whose
success is a property of the runner, since GitHub documents the default
GITHUB_* variables as not overwritable.

What has to hold, and none of it is observable from the auth step exiting zero:

- the file is no longer in the workspace, so a capture of the workspace cannot
  take it;
- no copy is left behind;
- all three environment variables consumers read are updated, including the one
  the upstream post step uses to clean up -- a move that stranded the cleanup
  would leave the credential on the runner.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "relocate-credential.sh"


@pytest.fixture
def env(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    github_env = tmp_path / "github-env"
    github_env.write_text("")
    return {
        "PATH": "/usr/bin:/bin",
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_ENV": str(github_env),
    }


def run(env, creds_path=None):
    e = dict(env)
    if creds_path is not None:
        e["GOOGLE_GHA_CREDS_PATH"] = str(creds_path)
    return subprocess.run(
        ["bash", str(SCRIPT)], env=e, capture_output=True, text=True
    )


def exported(env):
    lines = pathlib.Path(env["GITHUB_ENV"]).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_the_file_leaves_the_workspace(env):
    creds = pathlib.Path(env["GITHUB_WORKSPACE"]) / "gha-creds-deadbeef.json"
    creds.write_text('{"type":"external_account"}')

    result = run(env, creds)
    assert result.returncode == 0, result.stderr

    assert not creds.exists(), "the original is still in the workspace"
    workspace = pathlib.Path(env["GITHUB_WORKSPACE"])
    assert list(workspace.glob("gha-creds-*.json")) == [], "a copy was left behind"

    moved = pathlib.Path(env["RUNNER_TEMP"]) / "gcp-wif-auth" / "gha-creds-deadbeef.json"
    assert moved.read_text() == '{"type":"external_account"}'


def test_all_three_consumer_variables_follow_the_file(env):
    """The cleanup variable especially.

    The upstream post step removes whatever GOOGLE_GHA_CREDS_PATH names, read
    at cleanup time. Updating only the two variables consumers read would leave
    the credential on the runner after the job ended.
    """
    creds = pathlib.Path(env["GITHUB_WORKSPACE"]) / "gha-creds-deadbeef.json"
    creds.write_text("{}")

    assert run(env, creds).returncode == 0
    moved = str(
        pathlib.Path(env["RUNNER_TEMP"]) / "gcp-wif-auth" / "gha-creds-deadbeef.json"
    )
    got = exported(env)
    assert got["GOOGLE_APPLICATION_CREDENTIALS"] == moved
    assert got["CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"] == moved
    assert got["GOOGLE_GHA_CREDS_PATH"] == moved


def test_the_moved_file_is_not_readable_by_others(env):
    creds = pathlib.Path(env["GITHUB_WORKSPACE"]) / "gha-creds-deadbeef.json"
    creds.write_text("{}")
    creds.chmod(0o644)

    assert run(env, creds).returncode == 0
    moved = pathlib.Path(env["RUNNER_TEMP"]) / "gcp-wif-auth" / "gha-creds-deadbeef.json"
    assert moved.stat().st_mode & 0o077 == 0


def test_refuses_when_no_credential_was_created(env):
    result = run(env, None)
    assert result.returncode == 1
    assert "no credentials file was created" in result.stderr


def test_refuses_when_the_reported_path_does_not_exist(env):
    """A reported path that names nothing must not be reported as moved.

    Exiting zero here would leave every consumer pointed at a file that is not
    there, failing later and further from the cause.
    """
    missing = pathlib.Path(env["GITHUB_WORKSPACE"]) / "gha-creds-nothere.json"
    result = run(env, missing)
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_a_credential_already_outside_the_workspace_is_still_placed_and_exported(env):
    """If a future version writes elsewhere, this must stay correct.

    The script does not assume the source is in the workspace; it moves to a
    known location and exports that. A version bump that already writes outside
    the workspace must not make this a no-op that leaves the variables naming
    the old path.
    """
    elsewhere = pathlib.Path(env["RUNNER_TEMP"]) / "gha-creds-deadbeef.json"
    elsewhere.write_text("{}")

    assert run(env, elsewhere).returncode == 0
    moved = pathlib.Path(env["RUNNER_TEMP"]) / "gcp-wif-auth" / "gha-creds-deadbeef.json"
    assert moved.exists()
    assert exported(env)["GOOGLE_GHA_CREDS_PATH"] == str(moved)
