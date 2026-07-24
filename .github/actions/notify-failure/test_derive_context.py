"""Unit tests for derive_context.py — run with: python3 -m pytest -q"""
import json
import derive_context as dc


def _job(name, conclusion, steps):
    return {"name": name, "conclusion": conclusion,
            "steps": [{"name": n, "conclusion": c} for n, c in steps]}


def test_reports_first_failed_step_of_failed_job():
    jobs = [_job("build", "failure",
                 [("Checkout", "success"), ("Compile", "failure"), ("Upload", "skipped")])]
    assert dc.failed_units(jobs) == [("build", "Compile", "failure")]


def test_job_level_failure_has_no_step():
    jobs = [_job("build", "timed_out", [("Checkout", "success")])]
    assert dc.failed_units(jobs) == [("build", None, "timed_out")]


def test_ignores_successful_and_in_progress_jobs():
    jobs = [_job("ok", "success", [("A", "success")]),
            _job("notify-failure", None, []),
            _job("bad", "failure", [("A", "failure")])]
    assert dc.failed_units(jobs) == [("bad", "A", "failure")]


def test_reports_every_failed_job_in_order():
    jobs = [_job("a", "failure", [("X", "failure")]),
            _job("b", "cancelled", [])]
    assert dc.failed_units(jobs) == [("a", "X", "failure"), ("b", None, "cancelled")]


def test_hint_matches_on_step_name():
    hints = json.dumps({"Compile": "Check the toolchain pin."})
    text = dc.compose(
        workflow="Android Build", branch="main", actor="octocat",
        run_url="https://example/run/1",
        units=[("build", "Compile", "failure")], hints=hints)
    assert "*Hint:* Check the toolchain pin." in text
    assert "*Failed:* build / Compile" in text
    assert "Android Build" in text and "main" in text
    assert "@octocat" in text and "https://example/run/1" in text


def test_no_hint_line_when_step_unmatched():
    text = dc.compose(
        workflow="W", branch="main", actor="a", run_url="u",
        units=[("build", "Compile", "failure")], hints=json.dumps({"Other": "x"}))
    assert "*Hint:*" not in text


def test_job_level_failure_renders_conclusion():
    text = dc.compose(workflow="W", branch="main", actor="a", run_url="u",
                      units=[("build", None, "timed_out")], hints="")
    assert "*Failed:* build (timed_out, no failed step)" in text


def test_malformed_hints_are_ignored_not_fatal():
    text = dc.compose(workflow="W", branch="main", actor="a", run_url="u",
                      units=[("b", "S", "failure")], hints="{not json")
    assert "*Failed:* b / S" in text
    assert "*Hint:*" not in text


def test_committer_email_only_on_push():
    push_event = {"head_commit": {"author": {"email": "dev@example.com"}}}
    assert dc.committer_email("push", push_event) == "dev@example.com"
    assert dc.committer_email("schedule", {}) == ""
