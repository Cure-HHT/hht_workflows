"""Unit tests for the event-driven Validation Summary gate.

Run with:  cd .github/actions/validation-summary-gate && PYTHONPATH=. pytest tests/ -v

Verifies: HHT-OPS-composite-action-library/A+F

The gate's verdict is the merge decision for five repositories, so the cases
that matter most are the refusals: a failure blocks, a running check keeps it
pending, a cancelled check is never read as a pass, the gate never counts its
own check, and the evaluation fired by the last workflow to finish produces a
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


IGNORE = ["Validation Summary", "Validation Summary Gate"]


def ev_of(checks, runs=()):
    return gate.evaluate(list(checks), list(runs), check_name="Validation Summary",
                         ignore_workflows=IGNORE)


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
                "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(out),
                "INPUT_IGNORE_WORKFLOWS": "\n".join(IGNORE)}
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

def test_all_success_is_success():
    ev = ev_of([cr(1, "Build"), cr(2, "Validate PR Title")],
               [wr(500, "Build")])
    assert ev.verdict == "success"
    assert "all 2 check(s) passed" in ev.reason


def test_one_failure_is_failure():
    ev = ev_of([cr(1, "Build"), cr(2, "Lint", conclusion="failure")])
    assert ev.verdict == "failure"
    assert [i.name for i in ev.of("failed")] == ["Lint"]


@pytest.mark.parametrize("conclusion", ["timed_out", "action_required", "startup_failure",
                                        "stale", "something_new"])
def test_other_unsuccessful_conclusions_fail(conclusion):
    # Tightened on purpose: the polling gate let these through as "completed".
    assert ev_of([cr(1, "Build", conclusion=conclusion)]).verdict == "failure"


def test_one_in_progress_is_pending():
    ev = ev_of([cr(1, "Build"), cr(2, "Tests", status="in_progress", conclusion=None)])
    assert ev.verdict == "pending"
    assert [i.name for i in ev.of("pending")] == ["Tests"]


def test_failure_while_another_runs_stays_pending():
    # Acceptance: one failure and one running check stays pending, then fails.
    ev = ev_of([cr(1, "Lint", conclusion="failure"),
                cr(2, "Tests", status="in_progress", conclusion=None)])
    assert ev.verdict == "pending"
    title, summary = gate.render(ev, SHA)
    assert "1 already failed" in summary


def test_cancelled_is_pending_not_passing():
    ev = ev_of([cr(1, "Build"), cr(2, "Tests", conclusion="cancelled")])
    assert ev.verdict == "pending"
    assert ev.only_cancelled_pending
    assert [i.name for i in ev.of("cancelled")] == ["Tests"]


@pytest.mark.parametrize("conclusion", ["skipped", "neutral"])
def test_skipped_and_neutral_are_ok(conclusion):
    assert ev_of([cr(1, "Build"), cr(2, "Deploy", conclusion=conclusion)]).verdict == "success"


def test_self_named_checks_are_ignored():
    # The old polling job (failed, or still running) and an earlier gate check
    # run must not count -- otherwise the gate waits on, or fails because of,
    # itself.
    ev = ev_of([cr(1, "Build"),
                cr(2, "Validation Summary", status="in_progress", conclusion=None),
                cr(3, "Validation Summary", conclusion="failure")],
               [wr(500, "Build"), wr(501, "Validation Summary", status="in_progress", suite=2)])
    assert ev.verdict == "success"
    assert [i.name for i in ev.items] == ["Build"]


def test_ignored_workflow_checks_are_not_counted_under_other_names():
    ev = ev_of([cr(1, "Build"), cr(2, "Evaluate", status="in_progress", conclusion=None, suite=8)],
               [wr(600, "Validation Summary Gate", status="in_progress", suite=8)])
    assert ev.verdict == "success"


def test_newest_check_of_a_name_wins_regardless_of_api_order():
    # A failed run re-run to success: the newer id decides, whatever the order.
    ev = ev_of([cr(10, "Tests", conclusion="failure"), cr(20, "Tests", conclusion="success")])
    assert ev.verdict == "success"
    ev = ev_of([cr(20, "Tests", conclusion="failure"), cr(10, "Tests", conclusion="success")])
    assert ev.verdict == "failure"


def test_cancelled_superseded_by_a_queued_rerun_is_pending():
    # An `edited` event cancels the first metadata run and queues a second one
    # whose jobs have not created check runs yet.
    ev = ev_of([cr(1, "Validate PR Title", conclusion="cancelled", suite=1)],
               [wr(500, "PR Metadata", conclusion="cancelled", suite=1, workflow_id=5),
                wr(510, "PR Metadata", status="queued", conclusion=None, suite=2, workflow_id=5)])
    assert ev.verdict == "pending"
    assert not ev.only_cancelled_pending
    assert any(i.name == "workflow: PR Metadata" for i in ev.of("pending"))


def test_workflow_run_without_check_runs_yet_is_pending():
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Tests", status="queued", conclusion=None, suite=2)])
    assert ev.verdict == "pending"


def test_workflow_awaiting_approval_is_pending():
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Fork tests", conclusion="action_required", suite=2)])
    assert ev.verdict == "pending"
    assert ev.of("pending")[0].status == "awaiting approval"


def test_copilot_dynamic_runs_are_not_counted():
    ev = ev_of([cr(1, "Build"),
                cr(2, "copilot-pull-request-reviewer", status="in_progress",
                   conclusion=None, suite=9)],
               [wr(500, "Build"),
                wr(501, "Running Copilot Code Review", status="in_progress",
                   conclusion=None, suite=9, event="dynamic")])
    assert ev.verdict == "success"


def test_no_checks_at_all_is_not_a_pass():
    assert ev_of([], []).verdict == "pending"


def test_external_app_check_in_progress_is_pending():
    ev = ev_of([cr(1, "Build"),
                cr(2, "SonarCloud Code Analysis", status="in_progress", conclusion=None,
                   suite=77, app="sonarqubecloud")])
    assert ev.verdict == "pending"


def test_run_with_startup_failure_and_no_checks_fails():
    # A workflow with a YAML error never creates a job, so no check run says
    # it failed; the run itself does.
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Broken", conclusion="startup_failure", suite=2)])
    assert ev.verdict == "failure"
    assert [i.name for i in ev.of("failed")] == ["workflow: Broken"]


def test_run_that_failed_with_zero_jobs_fails():
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Lint", conclusion="failure", suite=2)])
    assert ev.verdict == "failure"


def test_failed_run_whose_failing_job_is_listed_is_not_double_counted():
    ev = ev_of([cr(1, "Lint", conclusion="failure", suite=2)],
               [wr(501, "Lint", conclusion="failure", suite=2)])
    assert [i.name for i in ev.of("failed")] == ["Lint"]


def test_run_cancelled_with_no_checks_is_pending():
    ev = ev_of([cr(1, "Build")],
               [wr(500, "Build"), wr(501, "Lint", conclusion="cancelled", suite=2)])
    assert ev.verdict == "pending" and ev.only_cancelled_pending


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


def test_newer_run_of_the_same_workflow_supersedes_its_older_checks():
    ev = ev_of([cr(10, "check", conclusion="failure", suite=1),
                cr(20, "check", conclusion="success", suite=2)],
               [wr(500, "W", conclusion="failure", suite=1, workflow_id=1),
                wr(510, "W", suite=2, workflow_id=1)])
    assert ev.verdict == "success"


def test_check_of_an_unknown_suite_is_keyed_by_suite():
    ev = ev_of([cr(10, "scan", conclusion="failure", suite=70, app="other"),
                cr(20, "scan", conclusion="success", suite=71, app="other")])
    assert ev.verdict == "failure"


# --------------------------------------------------------------------------
# trigger parsing
# --------------------------------------------------------------------------

def test_push_triggered_runs_are_ignored():
    trig, why = gate.parse_trigger("workflow_run", {"workflow_run": {
        "event": "push", "head_sha": SHA, "name": "Build"}}, IGNORE)
    assert trig is None and "not a pull request" in why


def test_own_and_polling_workflow_completions_are_ignored():
    for name in IGNORE:
        trig, why = gate.parse_trigger("workflow_run", {"workflow_run": {
            "event": "pull_request", "head_sha": SHA, "name": name}}, IGNORE)
        assert trig is None


def test_actions_check_run_events_are_ignored():
    trig, why = gate.parse_trigger("check_run", {"check_run": {
        "app": {"slug": "github-actions"}, "head_sha": SHA}}, IGNORE)
    assert trig is None


def test_malformed_sha_is_refused():
    trig, why = gate.parse_trigger("workflow_run", {"workflow_run": {
        "event": "pull_request", "head_sha": "main; rm -rf /", "name": "Build"}}, IGNORE)
    assert trig is None and "not a commit sha" in why


# --------------------------------------------------------------------------
# run(): effects
# --------------------------------------------------------------------------

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


def test_failure_updates_the_existing_comment_and_collapses_duplicates(tmp_path):
    fake = FakeGitHub([([cr(2, "Lint", conclusion="failure")], [])],
                      comments=[bot(12, "<!-- validation-summary -->\nlegacy"),
                                bot(11, gate.COMMENT_MARKER + "\ncurrent")])
    run_gate(tmp_path, fake)
    assert [p for m, p, _ in fake.writes("PATCH") if "/issues/" in p] == \
        [f"repos/{REPO}/issues/comments/11"]
    assert [p for m, p, _ in fake.writes("DELETE")] == [f"repos/{REPO}/issues/comments/12"]


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


def test_commit_that_is_not_an_open_pr_head_is_left_alone(tmp_path):
    fake = FakeGitHub([([cr(1, "Build", conclusion="failure")], [])],
                      prs=[{"number": 7, "head": {"sha": "b" * 40}}])
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 0 and fake.writes() == []
    assert any("not the head of an open pull request" in line for line in logs)


def test_pull_request_list_is_filtered_by_base_branch(tmp_path):
    fake = FakeGitHub([([cr(1, "Build")], [wr(500, "Build")])])
    run_gate(tmp_path, fake, INPUT_BASE_BRANCH="release")
    pulls = [params for m, p, params in fake.calls if p.endswith("/pulls")]
    assert pulls == [{"state": "open", "base": "release"}]


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


def test_external_check_run_event_is_evaluated(tmp_path):
    fake = FakeGitHub([([cr(1, "Build"), cr(2, "SonarCloud Code Analysis", suite=77,
                                             app="sonarqubecloud")],
                        [wr(500, "Build")])])
    event = {"action": "completed",
             "check_run": {"id": 2, "name": "SonarCloud Code Analysis", "head_sha": SHA,
                           "app": {"slug": "sonarqubecloud"}, "check_suite": {"id": 77}}}
    run_gate(tmp_path, fake, event_name="check_run", event=event)
    assert published(fake)["state"] == "success"


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


def test_run_cancelled_with_no_checks_becomes_failure_once_abandoned(tmp_path):
    state = ([cr(1, "Build", suite=1)],
             [wr(500, "Build", suite=1), wr(501, "Lint", conclusion="cancelled", suite=2)])
    slept = []
    fake = FakeGitHub([state])
    run_gate(tmp_path, fake, sleeps=slept)
    assert slept == [20.0, 20.0, 20.0]
    body = published(fake)
    assert body["state"] == "failure" and "workflow: Lint" in body["description"]


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


def test_publish_failure_is_reported_and_fails_the_job(tmp_path):
    class NoPost(FakeGitHub):
        def post(self, path, body):
            self.calls.append(("POST", path, body))
            raise RuntimeError("POST -> HTTP 500")
    fake = NoPost([([cr(1, "Build")], [wr(500, "Build")])])
    rc, logs, out = run_gate(tmp_path, fake)
    assert rc == 1
    assert [b["state"] for m, p, b in fake.calls if m == "POST"] == ["success", "error"]
    assert any("could not publish the error status" in line for line in logs)


# --------------------------------------------------------------------------
# real recorded check runs (fetched read-only from public hht_workflows PRs)
# --------------------------------------------------------------------------

def _fixture(name):
    data = json.loads((FIXTURES / name).read_text())
    return data


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_recorded_pr_reproduces_the_polling_gate_verdict(name):
    data = _fixture(name)
    ev = gate.evaluate(data["check_runs"], data["workflow_runs"],
                       check_name="Validation Summary", ignore_workflows=IGNORE)
    assert ev.verdict == data["expected_verdict"], (data["pr"], ev.reason)
    if data.get("polling_gate_conclusion"):
        assert {"success": "success", "failure": "failure"}[
            data["polling_gate_conclusion"]] == ev.verdict
