"""Unit tests for the event-driven Validation Summary gate.

Run with:  cd .github/actions/validation-summary-gate && PYTHONPATH=. pytest tests/ -v

The gate's verdict is the merge decision for five repositories, so the cases
that matter most are the refusals: a failure blocks, a running check keeps it
pending, a cancelled check is never read as a pass, nothing a pull request
can rename exempts a check, the gate never counts its own runs, and the evaluation fired by the last workflow to finish produces a
final verdict even when the API listing lags that event.
"""
from __future__ import annotations

import json
import pathlib

import pytest

import gate

SHA = "a" * 40
REPO = "Cure-HHT/example"
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def cr(cid, name, status="completed", conclusion="success", suite=1, app="github-actions",
       external_id=None):
    return {"id": cid, "name": name, "status": status, "conclusion": conclusion,
            "html_url": f"https://github.com/{REPO}/actions/runs/9/job/{cid}",
            "app": {"slug": app}, "check_suite": {"id": suite},
            "external_id": external_id}


def wr(rid, name, status="completed", conclusion="success", suite=1, event="pull_request",
       workflow_id=None):
    return {"id": rid, "name": name, "status": status, "conclusion": conclusion,
            "check_suite_id": suite, "event": event,
            "workflow_id": workflow_id if workflow_id is not None else hash(name) % 10000,
            "html_url": f"https://github.com/{REPO}/actions/runs/{rid}"}


GATE_PATH = gate.DEFAULT_GATE_WORKFLOW_PATH


def gate_run(rid, suite, status="completed", conclusion="success", event="workflow_run"):
    """A run of the gate's own workflow, as GitHub records it."""
    run = wr(rid, "Validation Summary Gate", status=status, conclusion=conclusion,
             suite=suite, event=event)
    run["path"] = GATE_PATH
    return run


def ev_of(checks, runs=()):
    return gate.evaluate(list(checks), list(runs))


class FakeGitHub:
    """Serves canned API state. `states` is a list of (check_runs, workflow_runs)
    returned by successive read_state calls; the last one repeats."""

    def __init__(self, states, prs=None, comments=None,
                 annotations=None, jobs=None):
        self.states = list(states)
        self.reads = 0
        self.prs = prs if prs is not None else [{"number": 7, "head": {"sha": SHA}}]
        self.comments = comments or []
        self.annotations = annotations or {}
        self.jobs = jobs or {}
        self.calls = []

    def _state(self):
        i = min(self.reads, len(self.states) - 1)
        return self.states[i]

    def paginate(self, path, params=None, key=None):
        self.calls.append(("GET", path, params))
        if path.endswith("/pulls"):
            return [p for p in self.prs]
        if path.endswith(f"/commits/{SHA}/check-runs"):
            checks = self._state()[0]
            return list(checks)
        if path.endswith("/actions/runs"):
            runs = self._state()[1]
            self.reads += 1     # one read_state = check-runs then runs
            return list(runs)
        if path.endswith("/annotations"):
            cid = int(path.split("/")[-2])
            return list(self.annotations.get(cid, []))
        if "/issues/" in path and path.endswith("/comments"):
            return list(self.comments)
        raise AssertionError(f"unexpected paginate {path}")

    def get(self, path, params=None):
        self.calls.append(("GET", path, params))
        jid = int(path.split("/")[-1])
        return self.jobs.get(jid, {"steps": []})

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        return {"id": 999}

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))
        return {"id": int(path.split("/")[-1])}

    def delete(self, path):
        self.calls.append(("DELETE", path, None))

    def writes(self, method=None):
        return [c for c in self.calls if c[0] != "GET" and (method is None or c[0] == method)]


def run_gate(tmp_path, fake, event_name="workflow_run", event=None, sleeps=None, **env):
    if event is None:
        event = {"action": "completed",
                 "workflow_run": {"id": 500, "name": "Build", "event": "pull_request",
                                  "head_sha": SHA, "check_suite_id": 1}}
    ep = tmp_path / "event.json"
    ep.write_text(json.dumps(event))
    summary = tmp_path / "summary.md"
    out = tmp_path / "out.txt"
    base_env = {"GITHUB_REPOSITORY": REPO, "GITHUB_EVENT_PATH": str(ep),
                "GITHUB_EVENT_NAME": event_name, "GITHUB_RUN_ID": "42",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(out)}
    base_env.update(env)
    slept = sleeps if sleeps is not None else []
    logs = []
    rc = gate.run(base_env, gh=fake, sleep=slept.append, now=lambda: "2026-10-12T00:00:00Z",
                  log=logs.append)
    return rc, logs, (out.read_text() if out.exists() else "")


def published(fake):
    """The body of the last commit status posted."""
    for method, path, body in reversed(fake.calls):
        if method == "POST" and path == f"repos/{REPO}/statuses/{SHA}":
            return body
    return None


def bot(cid, body):
    return {"id": cid, "body": body, "user": {"login": "github-actions[bot]"}}


# --------------------------------------------------------------------------
# evaluate(): the verdict table
# --------------------------------------------------------------------------

# Verifies: HHT-OPS-composite-action-library/A
def test_all_success_is_success():
    ev = ev_of([cr(1, "Build"), cr(2, "Validate PR Title")],
               [wr(500, "Build")])
    assert ev.verdict == "success"
    assert "all 2 check(s) passed" in ev.reason


# Verifies: HHT-OPS-composite-action-library/A
def test_one_failure_is_failure():
    ev = ev_of([cr(1, "Build"), cr(2, "Lint", conclusion="failure")])
    assert ev.verdict == "failure"
    assert [i.name for i in ev.of("failed")] == ["Lint"]


# Verifies: HHT-OPS-composite-action-library/A
@pytest.mark.parametrize("conclusion", ["timed_out", "action_required", "startup_failure",
                                        "stale", "something_new"])
# Verifies: HHT-OPS-composite-action-library/A
def test_other_unsuccessful_conclusions_fail(conclusion):
    # Tightened on purpose: the polling gate let these through as "completed".
    assert ev_of([cr(1, "Build", conclusion=conclusion)]).verdict == "failure"


# Verifies: HHT-OPS-composite-action-library/A
def test_one_in_progress_is_pending():
    ev = ev_of([cr(1, "Build"), cr(2, "Tests", status="in_progress", conclusion=None)])
    assert ev.verdict == "pending"
    assert [i.name for i in ev.of("pending")] == ["Tests"]


# Verifies: HHT-OPS-composite-action-library/A
def test_failure_while_another_runs_stays_pending():
    # Acceptance: one failure and one running check stays pending, then fails.
    ev = ev_of([cr(1, "Lint", conclusion="failure"),
                cr(2, "Tests", status="in_progress", conclusion=None)])
    assert ev.verdict == "pending"
    title, summary = gate.render(ev, SHA)
    assert "1 already failed" in summary


# Verifies: HHT-OPS-composite-action-library/A
def test_cancelled_is_pending_not_passing():
    ev = ev_of([cr(1, "Build"), cr(2, "Tests", conclusion="cancelled")])
    assert ev.verdict == "pending"
    assert ev.only_cancelled_pending
    assert [i.name for i in ev.of("cancelled")] == ["Tests"]


# Verifies: HHT-OPS-composite-action-library/A
@pytest.mark.parametrize("conclusion", ["skipped", "neutral"])
def test_skipped_and_neutral_are_ok(conclusion):
    assert ev_of([cr(1, "Build"), cr(2, "Deploy", conclusion=conclusion)]).verdict == "success"


# Verifies: HHT-OPS-composite-action-library/A
def test_polling_jobs_check_run_is_counted_like_any_other():
    # The old polling job's "Validation Summary" check run is counted: a
    # pull request can name any job that, so a name is never an exemption.
    running = ev_of([cr(1, "Build"), cr(2, "Validation Summary", status="in_progress",
                                         conclusion=None, suite=2)],
                    [wr(500, "Build"), wr(501, "Validation Summary", status="in_progress", suite=2)])
    assert running.verdict == "pending"
    failed = ev_of([cr(1, "Build"), cr(3, "Validation Summary", conclusion="failure", suite=2)],
                   [wr(500, "Build"), wr(501, "Validation Summary", conclusion="failure", suite=2)])
    assert failed.verdict == "failure"


# Verifies: HHT-OPS-composite-action-library/A
def test_own_gate_runs_are_not_counted():
    ev = ev_of([cr(1, "Build"), cr(2, "Evaluate", status="in_progress", conclusion=None, suite=8)],
               [wr(500, "Build"), gate_run(600, suite=8, status="in_progress", conclusion=None)])
    assert ev.verdict == "success"
    assert [i.name for i in ev.items] == ["Build"]


# Verifies: HHT-OPS-composite-action-library/A
@pytest.mark.parametrize("new_name", ["Validation Summary", "Validation Summary Gate"])
def test_renaming_a_failing_workflow_like_the_gate_does_not_exempt_it(new_name):
    # A pull request controls its workflows' names; renaming a failing one to
    # the gate's or the polling job's name must not turn the verdict green.
    ev = ev_of([cr(1, "Build"), cr(2, "tests", conclusion="failure", suite=2)],
               [wr(500, "Build"), wr(501, new_name, conclusion="failure", suite=2)])
    assert ev.verdict == "failure"


# Verifies: HHT-OPS-composite-action-library/A
def test_a_pr_workflow_in_the_gates_file_is_still_counted():
    # The gate's own file with a pull_request trigger added by the pull
    # request: same path, but a pull-request event, so it is counted.
    run = gate_run(601, suite=3, conclusion="failure", event="pull_request")
    ev = ev_of([cr(1, "Build"), cr(2, "Evaluate", conclusion="failure", suite=3)],
               [wr(500, "Build"), run])
    assert ev.verdict == "failure"


# Verifies: HHT-OPS-composite-action-library/A
def test_a_passing_workflow_named_like_the_gate_is_a_failure():
    # Its completion is excluded by the trigger filter and would never fire an
    # evaluation, so whatever it concludes later could go unseen.
    ev = ev_of([cr(1, "Build"), cr(2, "job", suite=2)],
               [wr(500, "Build"), wr(501, "Validation Summary Gate", suite=2)])
    assert ev.verdict == "failure"
    assert any(i.status == "Named like the gate" for i in ev.of("failed"))


# Verifies: HHT-OPS-composite-action-library/A
def test_newest_check_of_a_name_wins_regardless_of_api_order():
    # A failed run re-run to success: the newer id decides, whatever the order.
    ev = ev_of([cr(10, "Tests", conclusion="failure"), cr(20, "Tests", conclusion="success")])
    assert ev.verdict == "success"
    ev = ev_of([cr(20, "Tests", conclusion="failure"), cr(10, "Tests", conclusion="success")])
    assert ev.verdict == "failure"


# Verifies: HHT-OPS-composite-action-library/A
def test_cancelled_superseded_by_a_queued_rerun_is_pending():
    # An `edited` event cancels the first metadata run and queues a second one
    # whose jobs have not created check runs yet.
    ev = ev_of([cr(1, "Validate PR Title", conclusion="cancelled", suite=1)],
               [wr(500, "PR Metadata", conclusion="cancelled", suite=1, workflow_id=5),
                wr(510, "PR Metadata", status="queued", conclusion=None, suite=2, workflow_id=5)])
    assert ev.verdict == "pending"
    assert not ev.only_cancelled_pending
    assert any(i.name == "workflow: PR Metadata" for i in ev.of("pending"))


# Verifies: HHT-OPS-composite-action-library/A
def test_workflow_run_without_check_runs_yet_is_pending():
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Tests", status="queued", conclusion=None, suite=2)])
    assert ev.verdict == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_workflow_awaiting_approval_is_pending():
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Fork tests", conclusion="action_required", suite=2)])
    assert ev.verdict == "pending"
    assert ev.of("pending")[0].status == "awaiting approval"


# Verifies: HHT-OPS-composite-action-library/A
def test_copilot_dynamic_runs_are_not_counted():
    ev = ev_of([cr(1, "Build"),
                cr(2, "copilot-pull-request-reviewer", status="in_progress",
                   conclusion=None, suite=9)],
               [wr(500, "Build"),
                wr(501, "Running Copilot Code Review", status="in_progress",
                   conclusion=None, suite=9, event="dynamic")])
    assert ev.verdict == "success"


# Verifies: HHT-OPS-composite-action-library/A
def test_no_checks_at_all_is_not_a_pass():
    assert ev_of([], []).verdict == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_external_app_check_in_progress_is_pending():
    ev = ev_of([cr(1, "Build"),
                cr(2, "SonarCloud Code Analysis", status="in_progress", conclusion=None,
                   suite=77, app="sonarqubecloud")])
    assert ev.verdict == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_run_with_startup_failure_and_no_checks_fails():
    # A workflow with a YAML error never creates a job, so no check run says
    # it failed; the run itself does.
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Broken", conclusion="startup_failure", suite=2)])
    assert ev.verdict == "failure"
    assert [i.name for i in ev.of("failed")] == ["workflow: Broken"]


# Verifies: HHT-OPS-composite-action-library/A
def test_run_that_failed_with_zero_jobs_fails():
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Lint", conclusion="failure", suite=2)])
    assert ev.verdict == "failure"


# Verifies: HHT-OPS-composite-action-library/A
def test_failed_run_whose_failing_job_is_listed_is_not_double_counted():
    ev = ev_of([cr(1, "Lint", conclusion="failure", suite=2)],
               [wr(501, "Lint", conclusion="failure", suite=2)])
    assert [i.name for i in ev.of("failed")] == ["Lint"]


# Verifies: HHT-OPS-composite-action-library/A
def test_run_cancelled_with_no_checks_is_pending():
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Lint", conclusion="cancelled", suite=2)])
    assert ev.verdict == "pending" and ev.only_cancelled_pending


# Verifies: HHT-OPS-composite-action-library/A
def test_same_job_name_in_two_workflows_is_two_checks():
    # Two workflows in one consuming repository, validate-build-paths.yml and
    # validate-permissions-matrix.yml, both have a job called `check`. B's
    # failure must not hide behind A's pass.
    ev = ev_of([cr(10, "check", conclusion="failure", suite=1),
                cr(20, "check", conclusion="success", suite=2)],
               [wr(500, "Validate build paths allowlist", conclusion="failure", suite=1,
                   workflow_id=1),
                wr(501, "Validate permissions matrix", suite=2, workflow_id=2)])
    assert ev.verdict == "failure"
    assert [i.name for i in ev.of("failed")] == ["Validate build paths allowlist / check"]


# Verifies: HHT-OPS-composite-action-library/A
def test_newer_run_of_the_same_workflow_supersedes_its_older_checks():
    ev = ev_of([cr(10, "check", conclusion="failure", suite=1),
                cr(20, "check", conclusion="success", suite=2)],
               [wr(500, "W", conclusion="failure", suite=1, workflow_id=1),
                wr(510, "W", suite=2, workflow_id=1)])
    assert ev.verdict == "success"


# Verifies: HHT-OPS-composite-action-library/A
def test_check_of_an_unknown_suite_is_keyed_by_suite():
    ev = ev_of([cr(10, "scan", conclusion="failure", suite=70, app="other"),
                cr(20, "scan", conclusion="success", suite=71, app="other")])
    assert ev.verdict == "failure"


# --------------------------------------------------------------------------
# trigger parsing
# --------------------------------------------------------------------------

# Verifies: HHT-OPS-composite-action-library/A
@pytest.mark.parametrize("event", ["push", "pull_request_review", "workflow_dispatch",
                                   "pull_request", "pull_request_target"])
# Verifies: HHT-OPS-composite-action-library/A
def test_every_run_event_is_a_trigger(event):
    # A push, review, label, re-run or dispatch run on a PR head is counted,
    # so its start and end must each fire an evaluation.
    trig, why = gate.parse_trigger("workflow_run", {"action": "requested", "workflow_run": {
        "event": event, "head_sha": SHA, "name": "Build", "path": ".github/workflows/b.yml"}})
    assert trig is not None and trig["sha"] == SHA, why


# Verifies: HHT-OPS-composite-action-library/A
def test_only_the_gates_own_runs_are_skipped_as_triggers():
    own = {"event": "workflow_run", "head_sha": SHA, "name": "Validation Summary Gate",
           "path": GATE_PATH}
    trig, why = gate.parse_trigger("workflow_run", {"workflow_run": own})
    assert trig is None and "own workflow" in why
    for name in ("Validation Summary", "Validation Summary Gate"):
        trig, _ = gate.parse_trigger("workflow_run", {"workflow_run": {
            "event": "pull_request", "head_sha": SHA, "name": name,
            "path": ".github/workflows/renamed.yml"}})
        assert trig is not None


# Verifies: HHT-OPS-composite-action-library/A
def test_actions_check_run_events_are_ignored():
    trig, why = gate.parse_trigger("check_run", {"check_run": {
        "app": {"slug": "github-actions"}, "head_sha": SHA}})
    assert trig is None


# Verifies: HHT-OPS-composite-action-library/A
def test_malformed_sha_is_refused():
    trig, why = gate.parse_trigger("workflow_run", {"workflow_run": {
        "event": "pull_request", "head_sha": "main; rm -rf /", "name": "Build"}})
    assert trig is None and "not a commit sha" in why


# --------------------------------------------------------------------------
# run(): effects
# --------------------------------------------------------------------------

# Verifies: HHT-OPS-composite-action-library/A
def test_success_posts_success_status_and_clears_comments(tmp_path):
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])],
                      comments=[bot(11, gate.COMMENT_MARKER + "\nold"),
                                bot(12, "<!-- validation-summary -->\nolder"),
                                bot(13, "<!-- ci-gate-summary -->\noldest"),
                                bot(14, "unrelated")])
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 0
    body = published(fake)
    assert body["state"] == "success" and body["context"] == "Validation Summary"
    assert body["target_url"] == "https://github.com/Cure-HHT/example/actions/runs/42"
    assert len(body["description"]) <= 140
    assert not [c for c in fake.writes() if "/check-runs" in c[1]]   # no check run
    deleted = sorted(p for m, p, _ in fake.writes("DELETE"))
    assert deleted == [f"repos/{REPO}/issues/comments/{i}" for i in (11, 12, 13)]
    assert "verdict=success" in out


# Verifies: HHT-OPS-composite-action-library/A
def test_failure_posts_failure_status_and_comment_payload(tmp_path):
    fake = FakeGitHub(
        [([cr(1, "Build"), cr(2, "Lint", conclusion="failure"),
           cr(3, "Tests", conclusion="failure")], [wr(500, "Build")])],
        annotations={2: [{"annotation_level": "failure", "message": "line too long"},
                         {"annotation_level": "failure",
                          "message": "Process completed with exit code 1."},
                         {"annotation_level": "warning", "message": "ignored"}]},
        jobs={3: {"steps": [{"name": "Run tests", "conclusion": "failure"},
                            {"name": "Upload", "conclusion": "skipped"}]}})
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 0      # the verdict is the commit status, not this job's status
    body = published(fake)
    assert body["state"] == "failure"
    assert body["description"] == "2 of 3 check(s) failed: Lint, Tests"
    posts = [b for m, p, b in fake.writes("POST") if p.endswith("/issues/7/comments")]
    assert len(posts) == 1
    comment = posts[0]["body"]
    assert comment.startswith(gate.COMMENT_MARKER + "\n")
    assert "## Validation Summary: 2 of 3 check(s) failed" in comment
    assert "| :x: [Lint](" in comment and "line too long" in comment
    assert "exit code" not in comment
    assert "Failed step(s): Run tests" in comment
    assert "[View full details](https://github.com/Cure-HHT/example/actions/runs/42)" in comment


# Verifies: HHT-OPS-composite-action-library/A
def test_failure_updates_the_existing_comment_and_collapses_duplicates(tmp_path):
    fake = FakeGitHub([([cr(2, "Lint", conclusion="failure")], [])],
                      comments=[bot(12, "<!-- validation-summary -->\nlegacy"),
                                bot(11, gate.COMMENT_MARKER + "\ncurrent")])
    run_gate(tmp_path, fake)
    assert [p for m, p, _ in fake.writes("PATCH") if "/issues/" in p] == \
        [f"repos/{REPO}/issues/comments/11"]
    assert [p for m, p, _ in fake.writes("DELETE")] == [f"repos/{REPO}/issues/comments/12"]


# Verifies: HHT-OPS-composite-action-library/A
def test_comments_by_anyone_else_are_never_touched(tmp_path):
    # On a public repo anyone can post a comment that starts with the marker.
    planted = {"id": 21, "body": gate.COMMENT_MARKER + "\nplanted",
               "user": {"login": "someone"}}
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])], comments=[planted])
    run_gate(tmp_path, fake)
    assert fake.writes("DELETE") == [] and fake.writes("PATCH") == []
    fake = FakeGitHub([([cr(2, "Lint", conclusion="failure")], [])], comments=[planted])
    run_gate(tmp_path, fake)
    assert fake.writes("PATCH") == [] and fake.writes("DELETE") == []
    assert [p for m, p, _ in fake.writes("POST") if "/issues/" in p] == \
        [f"repos/{REPO}/issues/7/comments"]


# Verifies: HHT-OPS-composite-action-library/A
def test_in_progress_posts_pending_with_what_it_waits_for(tmp_path):
    fake = FakeGitHub([([cr(1, "Build", suite=1),
                         cr(2, "Tests", status="in_progress", conclusion=None, suite=2)],
                        [wr(500, "Build", suite=1),
                         wr(501, "Tests", status="in_progress", conclusion=None, suite=2)])],
                      comments=[bot(11, gate.COMMENT_MARKER + "\nfailed before")])
    rc, logs, out = run_gate(tmp_path, fake)
    body = published(fake)
    assert body["state"] == "pending"
    assert body["description"] == "Waiting for: Tests"
    assert not [c for c in fake.writes() if "/issues/" in c[1]]   # comment left alone
    assert "verdict=pending" in out
    summary = (tmp_path / "summary.md").read_text()
    assert "| :hourglass: Tests | in_progress |" in summary


# Verifies: HHT-OPS-composite-action-library/A
def test_pending_description_is_truncated_to_140(tmp_path):
    checks = [cr(i, f"a-rather-long-check-name-number-{i}", status="queued",
                 conclusion=None, suite=i) for i in range(1, 15)]
    runs = [wr(500 + i, f"W{i}", status="queued", conclusion=None, suite=i)
            for i in range(1, 15)]
    fake = FakeGitHub([(checks, runs)])
    event = {"action": "completed",
             "workflow_run": {"id": 999, "name": "Build", "event": "pull_request",
                              "head_sha": SHA, "check_suite_id": 99}}
    run_gate(tmp_path, fake, event=event, INPUT_RELIST_ATTEMPTS="0")
    desc = published(fake)["description"]
    assert len(desc) <= 140 and desc.startswith("Waiting for: ")


# Verifies: HHT-OPS-composite-action-library/A
def test_commit_that_is_not_an_open_pr_head_is_left_alone(tmp_path):
    fake = FakeGitHub([([cr(1, "Build", conclusion="failure")], [])],
                      prs=[{"number": 7, "head": {"sha": "b" * 40}}])
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 0 and fake.writes() == []
    assert any("not the head of an open pull request" in line for line in logs)


# Verifies: HHT-OPS-composite-action-library/A
def test_pull_request_list_is_filtered_by_base_branch(tmp_path):
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])])
    run_gate(tmp_path, fake, INPUT_BASE_BRANCH="release")
    pulls = [params for m, p, params in fake.calls if p.endswith("/pulls")]
    assert pulls == [{"state": "open", "base": "release"}]


# Verifies: HHT-OPS-composite-action-library/A
def test_fork_pr_is_matched_by_head_sha_not_by_event_pull_requests(tmp_path):
    # workflow_run.pull_requests is empty for fork PRs; the base repo's PR list
    # still names the head sha.
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])],
                      prs=[{"number": 9, "head": {"sha": SHA, "repo": {"fork": True}}}])
    event = {"action": "completed",
             "workflow_run": {"id": 500, "name": "Build", "event": "pull_request",
                              "head_sha": SHA, "check_suite_id": 1, "pull_requests": []}}
    run_gate(tmp_path, fake, event=event)
    assert published(fake)["state"] == "success"


# Verifies: HHT-OPS-composite-action-library/A
def test_external_check_run_event_is_evaluated(tmp_path):
    fake = FakeGitHub([([cr(1, "Build"), cr(2, "SonarCloud Code Analysis", suite=77,
                                             app="sonarqubecloud")],
                        [wr(500, "Build")])])
    event = {"action": "completed",
             "check_run": {"id": 2, "name": "SonarCloud Code Analysis", "head_sha": SHA,
                           "app": {"slug": "sonarqubecloud"}, "check_suite": {"id": 77}}}
    run_gate(tmp_path, fake, event_name="check_run", event=event)
    assert published(fake)["state"] == "success"


# Verifies: HHT-OPS-composite-action-library/A
def test_pending_on_another_apps_check_carries_rerun_guidance(tmp_path):
    # check_run may not fire for it (GitHub skips suites whose head SHA is
    # associated with GitHub Actions), so say how to un-stick it.
    fake = FakeGitHub([([cr(1, "Build"), cr(2, "SonarCloud Code Analysis", suite=77,
                                             status="in_progress", conclusion=None,
                                             app="sonarqubecloud")],
                        [wr(500, "Build")])])
    run_gate(tmp_path, fake)
    body = published(fake)
    assert body["state"] == "pending" and len(body["description"]) <= 140
    assert body["description"].endswith("(if stuck, re-run the Validation Summary Gate workflow)")
    assert "Re-run the latest **Validation Summary Gate**" in \
        (tmp_path / "summary.md").read_text()


# --------------------------------------------------------------------------
# the race: bounded re-list
# --------------------------------------------------------------------------

# Verifies: HHT-OPS-composite-action-library/A
def test_race_relist_reaches_final_verdict(tmp_path):
    # The run that fired this evaluation has completed, but the first listing
    # still shows its job running. The gate re-lists instead of publishing a
    # pending that no later event would correct.
    lagging = ([cr(1, "Build", status="in_progress", conclusion=None, suite=1),
                cr(2, "Lint", suite=2)],
               [wr(500, "Build", status="in_progress", conclusion=None, suite=1),
                wr(501, "Lint", suite=2)])
    caught_up = ([cr(1, "Build", suite=1), cr(2, "Lint", suite=2)],
                 [wr(500, "Build", suite=1), wr(501, "Lint", suite=2)])
    slept = []
    fake = FakeGitHub([lagging, caught_up])
    run_gate(tmp_path, fake, sleeps=slept)
    assert slept == [20.0]
    assert published(fake)["state"] == "success"


# Verifies: HHT-OPS-composite-action-library/A
def test_race_relist_is_bounded(tmp_path):
    lagging = ([cr(1, "Build", status="in_progress", conclusion=None, suite=1)],
               [wr(500, "Build", status="in_progress", conclusion=None, suite=1)])
    slept = []
    fake = FakeGitHub([lagging])
    run_gate(tmp_path, fake, sleeps=slept, INPUT_RELIST_ATTEMPTS="3",
             INPUT_RELIST_INTERVAL_SECONDS="20")
    assert slept == [20.0, 20.0, 20.0]
    body = published(fake)
    assert body["state"] == "pending"   # never a pass
    assert "re-run the Validation Summary Gate" in body["description"]


# Verifies: HHT-OPS-composite-action-library/A
def test_genuinely_running_check_does_not_trigger_relist(tmp_path):
    # Another workflow is still running for real: publish pending at once; its
    # own completion will fire the next evaluation.
    state = ([cr(1, "Build", suite=1),
              cr(2, "Tests", status="in_progress", conclusion=None, suite=2)],
             [wr(500, "Build", suite=1),
              wr(501, "Tests", status="in_progress", conclusion=None, suite=2)])
    slept = []
    run_gate(tmp_path, FakeGitHub([state]), sleeps=slept)
    assert slept == []


# Verifies: HHT-OPS-composite-action-library/A
def test_requested_event_publishes_pending_without_relisting(tmp_path):
    # An `edited` re-run of the metadata workflow: the gate goes pending at
    # once, as the polling gate did by restarting.
    state = ([cr(1, "Build", suite=1), cr(2, "Validate PR Title", suite=2)],
             [wr(500, "Build", suite=1),
              wr(510, "PR Metadata", status="queued", conclusion=None, suite=3)])
    event = {"action": "requested",
             "workflow_run": {"id": 510, "name": "PR Metadata", "event": "pull_request",
                              "head_sha": SHA, "check_suite_id": 3}}
    slept = []
    fake = FakeGitHub([state])
    run_gate(tmp_path, fake, event=event, sleeps=slept)
    assert slept == []
    body = published(fake)
    assert body["state"] == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_requested_event_relists_when_its_run_is_not_listed_yet(tmp_path):
    before = ([cr(1, "Build", suite=1)], [wr(500, "Build", suite=1)])
    after = ([cr(1, "Build", suite=1)],
             [wr(500, "Build", suite=1),
              wr(510, "PR Metadata", status="queued", conclusion=None, suite=3)])
    event = {"action": "requested",
             "workflow_run": {"id": 510, "name": "PR Metadata", "event": "pull_request",
                              "head_sha": SHA, "check_suite_id": 3}}
    slept = []
    fake = FakeGitHub([before, after])
    run_gate(tmp_path, fake, event=event, sleeps=slept)
    assert slept == [20.0]
    assert published(fake)["state"] == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_requested_run_never_listed_is_pending_not_success(tmp_path):
    # Everything listed has passed, but the run whose `requested` fired this
    # evaluation never shows up in the listing. Passing would pass without it.
    state = ([cr(1, "Build", suite=1)], [wr(500, "Build", suite=1)])
    event = {"action": "requested",
             "workflow_run": {"id": 510, "name": "PR Metadata", "event": "pull_request",
                              "head_sha": SHA, "check_suite_id": 3}}
    slept = []
    fake = FakeGitHub([state])
    run_gate(tmp_path, fake, event=event, sleeps=slept)
    assert slept == [20.0, 20.0, 20.0]
    body = published(fake)
    assert body["state"] == "pending"
    assert body["description"].endswith(
        "(if stuck, re-run the Validation Summary Gate workflow)")


# Verifies: HHT-OPS-composite-action-library/A
def test_completed_run_still_unfinished_after_relists_is_pending(tmp_path):
    lagging = ([cr(1, "Build", suite=1)],
               [wr(500, "Build", suite=1),
                wr(510, "Tests", status="in_progress", conclusion=None, suite=3)])
    event = {"action": "completed",
             "workflow_run": {"id": 510, "name": "Tests", "event": "pull_request",
                              "head_sha": SHA, "check_suite_id": 3}}
    fake = FakeGitHub([lagging])
    run_gate(tmp_path, fake, event=event, sleeps=[])
    assert published(fake)["state"] == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_external_check_created_after_a_pass_turns_pending_without_relisting(tmp_path):
    fake = FakeGitHub([([cr(1, "Build"), cr(2, "SonarCloud Code Analysis", suite=77,
                                             status="queued", conclusion=None,
                                             app="sonarqubecloud")],
                        [wr(500, "Build")])])
    event = {"action": "created",
             "check_run": {"id": 2, "name": "SonarCloud Code Analysis", "head_sha": SHA,
                           "app": {"slug": "sonarqubecloud"}, "check_suite": {"id": 77}}}
    slept = []
    run_gate(tmp_path, fake, event_name="check_run", event=event, sleeps=slept)
    assert slept == []
    assert published(fake)["state"] == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_external_check_not_listed_yet_is_never_a_pass(tmp_path):
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])])
    event = {"action": "created",
             "check_run": {"id": 2, "name": "SonarCloud Code Analysis", "head_sha": SHA,
                           "app": {"slug": "sonarqubecloud"}, "check_suite": {"id": 77}}}
    run_gate(tmp_path, fake, event_name="check_run", event=event, sleeps=[])
    assert published(fake)["state"] == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_cancelled_with_no_rerun_becomes_a_failure_after_the_relist(tmp_path):
    # The polling gate waited on this until its budget ran out and then failed.
    state = ([cr(1, "Build", suite=1), cr(2, "Tests", conclusion="cancelled", suite=2)],
             [wr(500, "Build", suite=1), wr(501, "Tests", conclusion="cancelled", suite=2)])
    slept = []
    fake = FakeGitHub([state])
    run_gate(tmp_path, fake, sleeps=slept)
    assert slept == [20.0, 20.0, 20.0]
    body = published(fake)
    assert body["state"] == "failure"
    assert "cancelled and not re-run: Tests" in body["description"]


# Verifies: HHT-OPS-composite-action-library/A
def test_cancelled_then_rerun_appears_during_relist(tmp_path):
    cancelled = ([cr(1, "Build", suite=1), cr(2, "Tests", conclusion="cancelled", suite=2)],
                 [wr(500, "Build", suite=1),
                  wr(501, "Tests", conclusion="cancelled", suite=2, workflow_id=4)])
    rerun = ([cr(1, "Build", suite=1), cr(2, "Tests", conclusion="cancelled", suite=2),
              cr(3, "Tests", conclusion="success", suite=3)],
             [wr(500, "Build", suite=1),
              wr(501, "Tests", conclusion="cancelled", suite=2, workflow_id=4),
              wr(502, "Tests", conclusion="success", suite=3, workflow_id=4)])
    slept = []
    fake = FakeGitHub([cancelled, rerun])
    run_gate(tmp_path, fake, sleeps=slept)
    assert slept == [20.0]
    assert published(fake)["state"] == "success"


# Verifies: HHT-OPS-composite-action-library/A
def test_api_error_fails_closed(tmp_path):
    class Broken(FakeGitHub):
        def paginate(self, path, params=None, key=None):
            if path.endswith("/actions/runs"):
                raise RuntimeError("GET runs -> HTTP 502")
            return super().paginate(path, params, key)
    fake = Broken([([cr(1, "Build")], [])])
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 1
    body = published(fake)
    assert body["state"] == "error" and "re-run the Validation Summary Gate" in body["description"]


# Verifies: HHT-OPS-composite-action-library/A
def test_run_cancelled_with_no_checks_becomes_failure_once_abandoned(tmp_path):
    state = ([cr(1, "Build", suite=1)],
             [wr(500, "Build", suite=1), wr(501, "Lint", conclusion="cancelled", suite=2)])
    slept = []
    fake = FakeGitHub([state])
    run_gate(tmp_path, fake, sleeps=slept)
    assert slept == [20.0, 20.0, 20.0]
    body = published(fake)
    assert body["state"] == "failure" and "workflow: Lint" in body["description"]


# Verifies: HHT-OPS-composite-action-library/A
def test_pulls_outage_fails_closed_with_an_error_status(tmp_path):
    class NoPulls(FakeGitHub):
        def paginate(self, path, params=None, key=None):
            if path.endswith("/pulls"):
                raise RuntimeError("GET pulls -> HTTP 503")
            return super().paginate(path, params, key)
    fake = NoPulls([([cr(1, "Build")], [])])
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 1
    assert published(fake)["state"] == "error"


# Verifies: HHT-OPS-composite-action-library/A
def test_publish_failure_is_reported_and_fails_the_job(tmp_path):
    class NoPost(FakeGitHub):
        def post(self, path, body):
            self.calls.append(("POST", path, body))
            raise RuntimeError("POST -> HTTP 500")
    fake = NoPost([([cr(1, "Build")], [wr(500, "Build")])])
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 1
    assert [b["state"] for m, p, b in fake.calls if m == "POST"] == ["pending", "error"]
    assert any("could not publish the error status" in line for line in logs)


# --------------------------------------------------------------------------
# fail-closed paths, pending-first, the job-failed mode, untrusted names
# --------------------------------------------------------------------------

def statuses(fake):
    return [b["state"] for m, p, b in fake.calls
            if m == "POST" and p == f"repos/{REPO}/statuses/{SHA}"]


# Verifies: HHT-OPS-composite-action-library/A
def test_pending_is_posted_before_the_verdict(tmp_path):
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])])
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 0 and statuses(fake) == ["pending", "success"]


# Verifies: HHT-OPS-composite-action-library/A
def test_check_runs_are_listed_with_filter_all(tmp_path):
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])])
    run_gate(tmp_path, fake)
    listed = [params for m, path, params in fake.calls if path.endswith("/check-runs")]
    assert listed and all(p and p.get("filter") == "all" for p in listed)


# Verifies: HHT-OPS-composite-action-library/A
def test_two_suites_sharing_a_job_name_fail_through_run(tmp_path):
    # With filter=all both same-named `check` jobs reach the per-workflow
    # dedupe; the failing one must decide the verdict.
    state = ([cr(10, "check", conclusion="success", suite=1),
              cr(20, "check", conclusion="failure", suite=2)],
             [wr(500, "Paths", suite=1, workflow_id=1),
              wr(501, "Permissions", conclusion="failure", suite=2, workflow_id=2)])
    fake = FakeGitHub([state])
    run_gate(tmp_path, fake)
    body = published(fake)
    assert body["state"] == "failure" and "Permissions / check" in body["description"]


# Verifies: HHT-OPS-composite-action-library/A
def test_a_push_run_on_a_pr_head_triggers_an_evaluation(tmp_path):
    event = {"action": "requested",
             "workflow_run": {"id": 700, "name": "Late", "event": "push",
                              "head_sha": SHA, "check_suite_id": 5}}
    state = ([cr(1, "Build"), cr(2, "late", status="in_progress", conclusion=None, suite=5)],
             [wr(500, "Build"), wr(700, "Late", status="in_progress", conclusion=None,
                                   suite=5, event="push")])
    fake = FakeGitHub([state])
    run_gate(tmp_path, fake, event=event, INPUT_RELIST_ATTEMPTS="0")
    assert published(fake)["state"] == "pending"


# Verifies: HHT-OPS-composite-action-library/A
def test_a_bad_input_posts_error_instead_of_leaving_a_pass(tmp_path):
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])])
    rc, logs, out = run_gate(tmp_path, fake, INPUT_RELIST_ATTEMPTS="three")
    assert rc == 1 and statuses(fake) == ["error"]


# Verifies: HHT-OPS-composite-action-library/A
def test_an_unreadable_event_fails_the_job_without_a_status(tmp_path):
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])])
    ep = tmp_path / "broken.json"
    ep.write_text("{not json")
    rc, logs, out = run_gate(tmp_path, fake, GITHUB_EVENT_PATH=str(ep))
    assert rc == 1 and statuses(fake) == []
    assert any("could not be determined" in line for line in logs)


def run_job_failed(tmp_path, fake, event=None):
    event = event or {"action": "completed",
                      "workflow_run": {"id": 500, "name": "Build", "event": "pull_request",
                                       "head_sha": SHA, "check_suite_id": 1}}
    ep = tmp_path / "event.json"
    ep.write_text(json.dumps(event))
    logs = []
    rc = gate.report_job_failure({"GITHUB_REPOSITORY": REPO, "GITHUB_EVENT_PATH": str(ep),
                                  "GITHUB_RUN_ID": "42", "INPUT_MODE": "job-failed"},
                                 gh=fake, sleep=lambda s: None, log=logs.append)
    return rc, logs


# Verifies: HHT-OPS-composite-action-library/A
def test_job_failed_mode_posts_error_on_an_open_pr_head(tmp_path):
    fake = FakeGitHub([([], [])])
    rc, logs = run_job_failed(tmp_path, fake)
    assert rc == 0 and statuses(fake) == ["error"]
    assert "cancelled" in published(fake)["description"]


# Verifies: HHT-OPS-composite-action-library/A
def test_job_failed_mode_leaves_a_non_pr_commit_alone(tmp_path):
    fake = FakeGitHub([([], [])], prs=[])
    rc, logs = run_job_failed(tmp_path, fake)
    assert rc == 0 and statuses(fake) == []


# Verifies: HHT-OPS-composite-action-library/A
def test_job_failed_mode_posts_error_when_prs_cannot_be_listed(tmp_path):
    class NoPulls(FakeGitHub):
        def paginate(self, path, params=None, key=None):
            if path.endswith("/pulls"):
                raise RuntimeError("GET pulls -> HTTP 503")
            return super().paginate(path, params, key)
    fake = NoPulls([([], [])])
    rc, logs = run_job_failed(tmp_path, fake)
    assert statuses(fake) == ["error"]


# Verifies: HHT-OPS-composite-action-library/A
def test_untrusted_names_cannot_inject_commands_or_mentions(tmp_path):
    evil = "lint\n::error::forged @maintainer"
    state = ([cr(1, "Build"), cr(2, evil, conclusion="failure", suite=2)],
             [wr(500, "Build"), wr(501, evil, conclusion="failure", suite=2)])
    fake = FakeGitHub([state], annotations={2: [{"annotation_level": "failure",
                                                 "message": "ping @owner\n::warning::x"}]})
    rc, logs, out = run_gate(tmp_path, fake)
    body = published(fake)
    comment = next(b["body"] for m, p, b in fake.calls if m == "POST" and p.endswith("/comments"))
    for text in (body["description"], comment, *logs):
        assert "\n::" not in text and "::error::forged" not in text
        assert "@maintainer" not in text and "@owner" not in text


# --------------------------------------------------------------------------
# real recorded check runs (fetched read-only from public hht_workflows PRs)
# --------------------------------------------------------------------------

def _fixture(name):
    data = json.loads((FIXTURES / name).read_text())
    return data


# Verifies: HHT-OPS-composite-action-library/A
@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_recorded_pr_reproduces_the_polling_gate_verdict(name):
    data = _fixture(name)
    ev = gate.evaluate(data["check_runs"], data["workflow_runs"])
    assert ev.verdict == data["expected_verdict"], (data["pr"], ev.reason)
    if data.get("polling_gate_conclusion"):
        assert {"success": "success", "failure": "failure"}[
            data["polling_gate_conclusion"]] == ev.verdict


# --------------------------------------------------------------------------
# the wrapper workflow: what fires the gate
# --------------------------------------------------------------------------

WRAPPERS = [
    pathlib.Path(__file__).resolve().parents[3] / "workflows" / "validation-summary-gate.yml",
]


# Verifies: HHT-OPS-composite-action-library/A
@pytest.mark.parametrize("wrapper", WRAPPERS, ids=lambda p: p.name)
def test_wrapper_selects_every_workflow_and_skips_itself_by_path(wrapper):
    text = wrapper.read_text()
    assert 'workflows: ["**"]' in text
    assert "!Validation Summary" not in text   # no name-based exclusion
    assert "types: [created, completed]" in text
    assert "github.event.workflow_run.path == '.github/workflows/validation-summary-gate.yml'" in text
    assert "github.event.workflow_run.name" not in text


# Verifies: HHT-OPS-composite-action-library/A
def test_readme_reference_matches_the_wrapper_trigger():
    readme = (pathlib.Path(gate.__file__).resolve().parent / "README.md").read_text()
    assert 'workflows: ["**"]' in readme and "types: [created, completed]" in readme
    assert "github.event.workflow_run.path == '.github/workflows/validation-summary-gate.yml'" in readme
