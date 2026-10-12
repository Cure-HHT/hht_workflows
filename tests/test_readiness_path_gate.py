"""Offline tests for the readiness-checks path gate (CUR-1030).

Verifies: HHT-OPS-composite-action-library/D — the per-action readiness checks
stay required and keep reporting on every pull request; the gate only lets an
unaffected one report `skipped`, and it never lets a fault in the decision turn
into a skip.

The decision is made by the `no-op` job's run body. These tests extract that
body verbatim from readiness-checks.yml, so they cannot drift from the
workflow, and drive it inside throwaway git repositories shaped like the
checkout a pull_request event produces: HEAD a merge commit whose first parent
is the base tip and whose second parent is the pull request's head.

The load-bearing cases are the refusals to narrow: a non-pull-request event, a
HEAD that is not a merge, and an edit to the workflow itself must all run every
gated job. A gate that only ever skipped would pass a happy-path test.
"""
import os
import pathlib
import subprocess

import pytest
import yaml

WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".github/workflows/readiness-checks.yml"
)
KEYS = {"cosign", "urs", "oq", "preflight"}
GATED = {
    "cosign-verify": "cosign",
    "build-urs": "urs",
    "build-oq": "oq",
    "sponsor-base-preflight": "preflight",
}


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _decide_body() -> str:
    steps = _doc()["jobs"]["no-op"]["steps"]
    bodies = [s["run"] for s in steps if s.get("id") == "decide"]
    assert len(bodies) == 1, "expected exactly one `decide` step in the no-op job"
    return bodies[0]


def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        },
    )


def _write(repo: pathlib.Path, rel: str, text: str = "x\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _repo(tmp_path: pathlib.Path, changed: list[str], merge: bool = True) -> pathlib.Path:
    """A repo whose HEAD is a test merge of a branch changing `changed`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "README.md")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "pr")
    for rel in changed:
        _write(repo, rel, "changed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "pr")
    if not merge:
        return repo
    _git(repo, "checkout", "-q", "main")
    # Move the base on, so the diff is proven to be against the base tip and
    # not to include what main changed meanwhile.
    _write(repo, ".github/fixtures/cosign-verify/moved-on-main.txt", "main moved\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main moves on")
    _git(repo, "merge", "-q", "--no-ff", "--no-edit", "pr")
    return repo


def _decide(repo: pathlib.Path, event: str = "pull_request") -> dict[str, str]:
    out = repo / "github_output"
    out.write_text("")
    proc = subprocess.run(
        ["bash", "-c", _decide_body()],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "EVENT": event, "GITHUB_OUTPUT": str(out)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    values = dict(line.split("=", 1) for line in out.read_text().splitlines() if line)
    assert set(values) == KEYS, f"decision must set every key once: {values}"
    return values


@pytest.mark.parametrize(
    "path,expected",
    [
        (".github/actions/cosign-verify/action.yml", {"cosign"}),
        (".github/fixtures/cosign-verify/Dockerfile", {"cosign"}),
        (".github/actions/build-urs/obtain-associates.sh", {"urs"}),
        ("scripts/urs-compile/compile-urs.py", {"urs"}),
        (".github/actions/build-oq/action.yml", {"oq"}),
        ("scripts/oq-compile/compile-oq.py", {"oq"}),
        (".github/actions/sponsor-base-preflight/preflight.py", {"preflight"}),
        ("README.md", set()),
        (".github/actions/gcp-wif-auth/action.yml", set()),
        # Prefix lookalikes must not match.
        (".github/actions/cosign-verify-extra/action.yml", set()),
        ("docs/scripts/urs-compile/notes.md", set()),
    ],
)
def test_each_job_runs_exactly_when_its_inputs_change(tmp_path, path, expected):
    values = _decide(_repo(tmp_path, [path]))
    assert {k for k, v in values.items() if v == "true"} == expected
    assert {k for k, v in values.items() if v == "false"} == KEYS - expected


def test_an_edit_to_the_workflow_runs_every_gated_job(tmp_path):
    values = _decide(_repo(tmp_path, [".github/workflows/readiness-checks.yml"]))
    assert values == {k: "true" for k in KEYS}


def test_base_side_changes_are_not_attributed_to_the_pull_request(tmp_path):
    # main moved cosign-verify after the branch point; the PR did not touch it.
    values = _decide(_repo(tmp_path, ["README.md"]))
    assert values["cosign"] == "false"


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "schedule"])
def test_anything_but_a_pull_request_runs_every_gated_job(tmp_path, event):
    values = _decide(_repo(tmp_path, ["README.md"]), event=event)
    assert values == {k: "true" for k in KEYS}


def test_a_head_that_is_not_a_merge_runs_every_gated_job(tmp_path):
    values = _decide(_repo(tmp_path, ["README.md"], merge=False))
    assert values == {k: "true" for k in KEYS}


def test_gated_jobs_keep_their_required_names_and_fail_closed():
    jobs = _doc()["jobs"]
    for job_id, key in GATED.items():
        job = jobs[job_id]
        # The reported check name is the bare job id the ruleset requires.
        assert "name" not in job, f"{job_id} must keep reporting its bare id"
        assert job.get("needs") == ["no-op"], job_id
        condition = job.get("if", "")
        assert "!cancelled()" in condition, job_id
        # A failed or skipped decision must run the job, not skip it.
        assert "needs.no-op.result != 'success'" in condition, job_id
        assert f"needs.no-op.outputs.{key} == 'true'" in condition, job_id
        assert f"${{{{ steps.decide.outputs.{key} }}}}" == jobs["no-op"]["outputs"][key]


def test_the_workflow_still_reports_on_every_pull_request():
    doc = _doc()
    # PyYAML reads the `on` key as boolean True.
    triggers = doc.get("on", doc.get(True))
    assert triggers["pull_request"] in ({}, None), (
        "pull_request must stay unfiltered so every required context reports"
    )
