"""Unit tests for derive_context.py — run with: python3 -m pytest -q"""
import json
import subprocess

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


# --- _fetch_jobs -----------------------------------------------------------
#
# The fake stands in for the real `gh api` framing rules: WITHOUT `--jq`,
# --paginate concatenates each page's body with no separator and no trailing
# newline (so a 2-page response is a single unparseable line); WITH `--jq`,
# gh emits one compact JSON value per line, uniformly across pages.

def _fake_gh(pages):
    def run(argv, **kwargs):
        assert argv[:2] == ["gh", "api"]
        if "--jq" in argv:
            expr = argv[argv.index("--jq") + 1]
            assert expr == ".jobs[]"
            body = "".join(
                "".join(json.dumps(job, separators=(",", ":")) + "\n"
                        for job in page["jobs"])
                for page in pages)
        else:
            body = "".join(json.dumps(page) for page in pages)  # no separator!
        return subprocess.CompletedProcess(argv, 0, stdout=body, stderr="")
    return run


def test_fetch_jobs_parses_a_single_page(monkeypatch):
    page = {"total_count": 2, "jobs": [
        _job("build", "failure", [("Compile", "failure")]),
        _job("notify", None, []),
    ]}
    monkeypatch.setattr(dc.subprocess, "run", _fake_gh([page]))
    jobs = dc._fetch_jobs("Cure-HHT/hht_workflows", "123")
    assert [j["name"] for j in jobs] == ["build", "notify"]
    assert jobs[0]["steps"][0]["conclusion"] == "failure"


def test_fetch_jobs_parses_every_page(monkeypatch):
    """Regression: a 2+ page response used to parse as zero jobs."""
    pages = [
        {"total_count": 4, "jobs": [_job("p1a", "success", []),
                                    _job("p1b", "success", [])]},
        {"total_count": 4, "jobs": [_job("p2a", "success", []),
                                    _job("p2b", "failure", [("Late", "failure")])]},
    ]
    monkeypatch.setattr(dc.subprocess, "run", _fake_gh(pages))
    jobs = dc._fetch_jobs("Cure-HHT/hht_workflows", "123")
    assert [j["name"] for j in jobs] == ["p1a", "p1b", "p2a", "p2b"]
    # The failure lives on the SECOND page — the case that used to be lost.
    assert dc.failed_units(jobs) == [("p2b", "Late", "failure")]


def test_fetch_jobs_requests_a_full_page_and_paginates(monkeypatch):
    seen = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(dc.subprocess, "run", run)
    assert dc._fetch_jobs("o/r", "9") == []
    assert "--paginate" in seen["argv"]
    assert "repos/o/r/actions/runs/9/jobs?per_page=100" in seen["argv"]


# --- main / $GITHUB_OUTPUT -------------------------------------------------

def _run_main(monkeypatch, tmp_path, jobs, *, event_name="push",
              event=None, hints=""):
    out_file = tmp_path / "github_output"
    out_file.write_text("")
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(event if event is not None else {}))

    for key, value in {
        "GITHUB_REPOSITORY": "Cure-HHT/hht_workflows",
        "GITHUB_RUN_ID": "42",
        "GITHUB_WORKFLOW": "Android Build",
        "GITHUB_REF_NAME": "main",
        "GITHUB_ACTOR": "octocat",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_EVENT_PATH": str(event_file),
        "GITHUB_OUTPUT": str(out_file),
        "INPUT_HINTS": hints,
    }.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(dc, "_fetch_jobs", lambda repo, run_id: jobs)
    dc.main()
    return out_file.read_text()


def _parse_output(text):
    """Minimal $GITHUB_OUTPUT reader with the same heredoc rules Actions uses."""
    values, lines, i = {}, text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line:
            key, delim = line.split("<<", 1)
            body = []
            i += 1
            while i < len(lines) and lines[i] != delim:
                body.append(lines[i])
                i += 1
            values[key] = "\n".join(body)
        elif "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
        i += 1
    return values


def test_main_writes_text_block_and_committer_email(monkeypatch, tmp_path):
    jobs = [_job("build", "failure", [("Compile", "failure")])]
    event = {"head_commit": {"author": {"email": "dev@example.com"}}}
    written = _run_main(monkeypatch, tmp_path, jobs, event=event)
    values = _parse_output(written)

    assert values["committer-email"] == "dev@example.com"
    assert "*Failed:* build / Compile" in values["text"]
    assert "Android Build" in values["text"]
    assert "https://github.com/Cure-HHT/hht_workflows/actions/runs/42" in values["text"]
    # Multi-line body really is wrapped in a heredoc, not a `key=value` line.
    assert "\n" in values["text"]


def test_main_delimiter_is_not_forgeable(monkeypatch, tmp_path):
    """Hint text containing the old fixed literal must not truncate output."""
    hints = json.dumps({"Compile": "boom\n__NF_EOF__\ninjected=pwned"})
    jobs = [_job("build", "failure", [("Compile", "failure")])]
    written = _run_main(monkeypatch, tmp_path, jobs, hints=hints)
    values = _parse_output(written)

    assert "injected" not in values          # no smuggled output key
    assert "__NF_EOF__" in values["text"]    # kept inside the block, inert
    assert "committer-email" in values       # nothing after it was swallowed
    assert values["text"].rstrip().endswith(
        "https://github.com/Cure-HHT/hht_workflows/actions/runs/42")


def test_main_survives_an_unreadable_event_payload(monkeypatch, tmp_path):
    """An advisory DM lookup must never suppress the announcement."""
    jobs = [_job("build", "failure", [("Compile", "failure")])]
    out_file = tmp_path / "github_output"
    out_file.write_text("")
    bad_event = tmp_path / "bad.json"
    bad_event.write_text("{not json")

    for key, value in {
        "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "1",
        "GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": str(bad_event),
        "GITHUB_OUTPUT": str(out_file), "INPUT_HINTS": "",
    }.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(dc, "_fetch_jobs", lambda repo, run_id: jobs)
    dc.main()

    values = _parse_output(out_file.read_text())
    assert values["committer-email"] == ""
    assert "*Failed:* build / Compile" in values["text"]
