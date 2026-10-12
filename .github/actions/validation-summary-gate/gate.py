#!/usr/bin/env python3
"""Validation Summary gate -- event-driven evaluation.

One evaluation of the "Validation Summary" required check for one commit.
The caller is a workflow triggered by `workflow_run` (every PR workflow
finishing, plus the start of the workflows that re-run on `edited`) and by
`check_run: completed` (check runs posted by GitHub Apps other than
GitHub Actions). Each firing reads the commit's check runs and workflow
runs ONCE, decides, and publishes a check run named "Validation Summary"
on the commit through the Checks API. Nothing waits on a runner: the next
completion is the next evaluation.

Semantics carried over unchanged from the polling gate it replaces
(.github/actions/validation-summary): every check run on the head commit
counts except those named like the gate itself; the newest check run of
each name wins; skipped and neutral are passing; cancelled means "waiting
for a re-run"; the gate fails, and upserts one PR comment naming the
failed checks with their annotations, once every check has completed and
any failed. Differences, each fail-closed:

- timed_out, action_required, startup_failure and stale count as failed.
  The polling gate counted only `failure` and let the others pass.
- A workflow run still queued, in progress, waiting, or awaiting approval
  on the commit is pending even before its jobs have created check runs.
- A cancelled check with no re-run anywhere in sight is reported as a
  failure instead of being waited on until a timeout. The polling gate
  reached the same verdict, after its 30 (or 185) minute budget.

Runs of the `dynamic` event (GitHub's Copilot code-review agent) are not
counted: they are triggered by a review request, not by the pull request
event, they validate nothing, and no event is documented to fire when they
finish, so waiting on one could leave the gate pending for good.

Implements: HHT-OPS-composite-action-library/A+F
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable

API_VERSION = "2022-11-28"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# The gate's own check runs carry this external_id so it can find and update
# them while another check run of the same name (the old polling job, during
# the transition) exists on the same commit.
GATE_EXTERNAL_ID = "validation-summary-gate"

# The current PR-comment marker (pr-comment-upsert convention), then the two
# earlier generations. A failure upserts the current one; a pass removes all.
COMMENT_MARKER = "<!-- pr-comment-upsert:validation-summary -->"
LEGACY_COMMENT_MARKERS = ("<!-- validation-summary -->", "<!-- ci-gate-summary -->")

OK_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
FAILED_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "action_required", "startup_failure", "stale"})
IGNORED_RUN_EVENTS = frozenset({"dynamic"})
PR_EVENTS = frozenset({"pull_request", "pull_request_target"})

# Annotation lines that say nothing beyond "it failed".
_NOISE = re.compile(
    r"Process completed with exit code|^Unexpected failure|^Failed during:")

SUMMARY_LIMIT = 60000   # Checks API output.summary maximum is 65535.


# --------------------------------------------------------------------------
# Evaluation (pure)
# --------------------------------------------------------------------------

@dataclasses.dataclass
class Item:
    name: str
    state: str          # ok | failed | pending | cancelled
    status: str         # human-readable status column
    url: str = ""
    check_id: int | None = None
    app: str = ""
    suite_id: int | None = None
    detail: str = ""


@dataclasses.dataclass
class Evaluation:
    verdict: str                    # success | failure | pending
    items: list[Item]
    reason: str = ""

    def of(self, state: str) -> list[Item]:
        return [i for i in self.items if i.state == state]

    @property
    def counted(self) -> list[Item]:
        """Items that are check runs (workflow-run placeholders excluded)."""
        return [i for i in self.items if i.check_id is not None]

    @property
    def only_cancelled_pending(self) -> bool:
        return (self.verdict == "pending" and not self.of("pending")
                and bool(self.of("cancelled")))


def latest_per_name(check_runs: Iterable[dict]) -> list[dict]:
    """Newest check run of each name.

    Decided by id (ids increase with creation) rather than by API order, which
    the polling gate assumed to be newest-first.
    """
    best: dict[str, dict] = {}
    for cr in check_runs:
        cur = best.get(cr["name"])
        if cur is None or cr["id"] > cur["id"]:
            best[cr["name"]] = cr
    return sorted(best.values(), key=lambda c: c["name"])


def latest_runs(workflow_runs: Iterable[dict]) -> list[dict]:
    """Newest run of each (workflow, event) on the commit."""
    best: dict[tuple, dict] = {}
    for run in workflow_runs:
        key = (run.get("workflow_id") or run.get("name"), run.get("event"))
        cur = best.get(key)
        if cur is None or run["id"] > cur["id"]:
            best[key] = run
    return list(best.values())


# Implements: HHT-OPS-composite-action-library/A
def evaluate(check_runs: list[dict], workflow_runs: list[dict], *,
             check_name: str, ignore_workflows: Iterable[str]) -> Evaluation:
    ignore_workflows = set(ignore_workflows)
    ignored_suites = {
        r.get("check_suite_id") for r in workflow_runs
        if r.get("name") in ignore_workflows
        or r.get("event") in IGNORED_RUN_EVENTS
    } - {None}
    relevant = [
        cr for cr in check_runs
        if cr["name"] != check_name
        and (cr.get("check_suite") or {}).get("id") not in ignored_suites
    ]
    items: list[Item] = []
    suites_with_pending: set = set()
    for cr in latest_per_name(relevant):
        status, conclusion = cr.get("status"), cr.get("conclusion")
        item = Item(name=cr["name"], state="ok", status="",
                    url=cr.get("html_url") or "", check_id=cr["id"],
                    app=((cr.get("app") or {}).get("slug") or ""),
                    suite_id=(cr.get("check_suite") or {}).get("id"))
        if status != "completed":
            item.state, item.status = "pending", status or "queued"
            suites_with_pending.add(item.suite_id)
        elif conclusion == "cancelled":
            item.state, item.status = "cancelled", "Cancelled, awaiting re-run"
        elif conclusion in FAILED_CONCLUSIONS:
            item.state = "failed"
            item.status = "Failed" if conclusion == "failure" else conclusion
        elif conclusion in OK_CONCLUSIONS:
            item.status = conclusion.capitalize()
        else:   # an unknown conclusion is not evidence of success
            item.state, item.status = "failed", str(conclusion)
        items.append(item)

    for run in latest_runs(workflow_runs):
        if run.get("name") in ignore_workflows or run.get("event") in IGNORED_RUN_EVENTS:
            continue
        status, conclusion = run.get("status"), run.get("conclusion")
        if status != "completed":
            label = status or "queued"
        elif conclusion == "action_required":
            label = "awaiting approval"
        else:
            continue
        if run.get("check_suite_id") in suites_with_pending:
            continue    # already listed through its pending check runs
        items.append(Item(name=f"workflow: {run.get('name')}", state="pending",
                          status=label, url=run.get("html_url") or "",
                          suite_id=run.get("check_suite_id")))

    pending = [i for i in items if i.state in ("pending", "cancelled")]
    failed = [i for i in items if i.state == "failed"]
    if pending:
        return Evaluation("pending", items,
                          f"waiting on {len(pending)} check(s)")
    if not [i for i in items if i.check_id is not None]:
        return Evaluation("pending", items, "no check runs reported yet")
    if failed:
        return Evaluation("failure", items,
                          f"{len(failed)} of {len(items)} check(s) failed")
    return Evaluation("success", items,
                      f"all {len(items)} check(s) passed (or were skipped)")


def looks_stale(ev: Evaluation, workflow_runs: list[dict],
                trigger: dict) -> bool:
    """True when the listing visibly lags the event that fired this run.

    `completed` is delivered only once its run (or check run) has finished,
    so seeing that run unfinished -- or missing, or any check run of a suite
    whose workflow run already reads `completed` still pending -- means the
    API has not caught up yet. `requested` is delivered once the run exists,
    so a listing without it is behind. A cancelled-only wait also re-lists,
    to give a re-run time to appear before it is called abandoned.
    """
    if ev.only_cancelled_pending:
        return True
    runs_by_id = {r.get("id"): r for r in workflow_runs}
    if trigger.get("kind") == "workflow_run":
        run = runs_by_id.get(trigger.get("run_id"))
        if run is None:
            return True
        if trigger.get("action") == "completed":
            if run.get("status") != "completed":
                return True
            if any(i.suite_id == trigger.get("suite_id") and i.check_id is not None
                   for i in ev.of("pending")):
                return True
    elif trigger.get("kind") == "check_run":
        if any(i.check_id == trigger.get("check_id") for i in ev.of("pending")):
            return True
    completed_suites = {r.get("check_suite_id") for r in workflow_runs
                        if r.get("status") == "completed"}
    return any(i.check_id is not None and i.suite_id in completed_suites
               for i in ev.of("pending"))


# --------------------------------------------------------------------------
# Rendering (pure)
# --------------------------------------------------------------------------

def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def render(ev: Evaluation, sha: str) -> tuple[str, str]:
    """(title, markdown summary) for the check run, the step summary and the
    PR comment. The table matches the polling gate's comment."""
    failed = ev.of("failed")
    if ev.verdict == "failure":
        cancelled = ev.of("cancelled")
        head = (f"## Validation Summary: {len(failed)} of {len(ev.items)} "
                f"check(s) failed")
        if cancelled and not failed:
            head = (f"## Validation Summary: {len(cancelled)} check(s) "
                    f"cancelled and not re-run")
        title = ev.reason
    elif ev.verdict == "pending":
        waiting = [i for i in ev.items if i.state in ("pending", "cancelled")]
        head = f"## Validation Summary: waiting on {len(waiting)} check(s)"
        if failed:
            head += f" ({len(failed)} already failed)"
        title = ev.reason
    else:
        head = f"## Validation Summary: {ev.reason}"
        title = ev.reason

    rows = []
    order = {"failed": 0, "cancelled": 1, "pending": 2, "ok": 3}
    for i in sorted(ev.items, key=lambda x: (order[x.state], x.name)):
        if i.state == "failed":
            name = f"[{_cell(i.name)}]({i.url})" if i.url else _cell(i.name)
            rows.append(f"| :x: {name} | {_cell(i.status)} | {_cell(i.detail)} |")
        elif i.state == "cancelled":
            rows.append(f"| :warning: {_cell(i.name)} | {_cell(i.status)} | |")
        elif i.state == "pending":
            rows.append(f"| :hourglass: {_cell(i.name)} | {_cell(i.status)} | |")
        else:
            rows.append(f"| :white_check_mark: {_cell(i.name)} | {_cell(i.status)} | |")
    body = "\n".join([
        head, "",
        f"Commit `{sha[:7]}`", "",
        "| Check | Status | Details |",
        "|-------|--------|---------|",
        *rows,
    ])
    if len(body) > SUMMARY_LIMIT:
        body = body[:SUMMARY_LIMIT] + "\n\n_(truncated)_"
    return title[:1000], body


def comment_body(summary: str, details_url: str, now: str) -> str:
    return (f"{COMMENT_MARKER}\n{summary}\n\n"
            f"*Updated: {now} | [View full details]({details_url})*")


def failure_detail(annotations: list[dict], failed_steps: list[str]) -> str:
    msgs = []
    for a in annotations:
        if a.get("annotation_level") != "failure":
            continue
        for line in str(a.get("message") or "").splitlines():
            line = line.strip()
            if line and not _NOISE.search(line) and line not in msgs:
                msgs.append(line)
    if msgs:
        return "; ".join(msgs[:3])
    if failed_steps:
        return "Failed step(s): " + ", ".join(failed_steps)
    return ""


# --------------------------------------------------------------------------
# Trigger parsing
# --------------------------------------------------------------------------

def parse_trigger(event_name: str, event: dict, ignore_workflows: Iterable[str]):
    """Return (trigger dict, None) or (None, reason-to-skip)."""
    if event_name == "workflow_run":
        run = event.get("workflow_run") or {}
        if run.get("event") not in PR_EVENTS:
            return None, f"triggering run's event is {run.get('event')!r}, not a pull request"
        if run.get("name") in set(ignore_workflows):
            return None, f"triggering workflow {run.get('name')!r} is ignored"
        trig = {"kind": "workflow_run", "sha": run.get("head_sha") or "",
                "run_id": run.get("id"), "suite_id": run.get("check_suite_id"),
                "name": run.get("name"), "action": event.get("action")}
    elif event_name == "check_run":
        cr = event.get("check_run") or {}
        if ((cr.get("app") or {}).get("slug")) == "github-actions":
            return None, "check run was created by GitHub Actions"
        trig = {"kind": "check_run", "sha": cr.get("head_sha") or "",
                "check_id": cr.get("id"),
                "suite_id": (cr.get("check_suite") or {}).get("id"),
                "name": cr.get("name"), "action": event.get("action")}
    else:
        return None, f"unsupported event {event_name!r}"
    if not SHA_RE.match(trig["sha"]):
        return None, f"head sha {trig['sha']!r} is not a commit sha"
    return trig, None


# --------------------------------------------------------------------------
# GitHub REST client
# --------------------------------------------------------------------------

class GitHub:
    def __init__(self, token: str, api: str = "https://api.github.com",
                 sleep: Callable[[float], None] = time.sleep):
        self.token, self.api, self.sleep = token, api.rstrip("/"), sleep

    def _request(self, method: str, url: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(4):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "hht-workflows-validation-summary-gate",
                **({"Content-Type": "application/json"} if data else {}),
            })
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read()
                    return (json.loads(raw) if raw else None), resp.headers
            except urllib.error.HTTPError as exc:
                retryable = exc.code >= 500 or exc.code == 429 or (
                    exc.code == 403 and exc.headers.get("x-ratelimit-remaining") == "0")
                if not retryable or attempt == 3:
                    detail = exc.read().decode(errors="replace")[:300]
                    raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                if attempt == 3:
                    raise RuntimeError(f"{method} {url} -> {exc.reason}") from exc
            self.sleep(min(60, 5 * 2 ** attempt))
        raise RuntimeError("unreachable")

    def _url(self, path: str, params: dict | None = None) -> str:
        url = f"{self.api}/{path.lstrip('/')}"
        return url + ("?" + urllib.parse.urlencode(params) if params else "")

    def get(self, path: str, params: dict | None = None):
        return self._request("GET", self._url(path, params))[0]

    def paginate(self, path: str, params: dict | None = None, key: str | None = None) -> list:
        params = {"per_page": 100, **(params or {})}
        url, out = self._url(path, params), []
        while url:
            data, headers = self._request("GET", url)
            out.extend(data.get(key, []) if key else data)
            url = None
            for part in (headers.get("Link") or "").split(","):
                m = re.search(r'<([^>]+)>;\s*rel="next"', part)
                if m:
                    url = m.group(1)
        return out

    def post(self, path: str, body: dict):
        return self._request("POST", self._url(path), body)[0]

    def patch(self, path: str, body: dict):
        return self._request("PATCH", self._url(path), body)[0]

    def delete(self, path: str):
        return self._request("DELETE", self._url(path))[0]


# --------------------------------------------------------------------------
# Effects
# --------------------------------------------------------------------------

def open_prs_for(gh, repo: str, sha: str, base: str) -> list[int]:
    """Open PRs into `base` whose CURRENT head is `sha`.

    Matched on the base repository's PR list rather than the event's
    `pull_requests` array, which is empty for pull requests from forks.
    """
    prs = gh.paginate(f"repos/{repo}/pulls", {"state": "open", "base": base})
    return sorted(p["number"] for p in prs if (p.get("head") or {}).get("sha") == sha)


def read_state(gh, repo: str, sha: str) -> tuple[list[dict], list[dict]]:
    checks = gh.paginate(f"repos/{repo}/commits/{sha}/check-runs", key="check_runs")
    runs = gh.paginate(f"repos/{repo}/actions/runs", {"head_sha": sha},
                       key="workflow_runs")
    return checks, runs


def evaluate_with_relist(gh, repo: str, sha: str, trigger: dict, *,
                         check_name: str, ignore_workflows: list[str],
                         attempts: int, interval: float,
                         sleep: Callable[[float], None], log=print):
    """Evaluate, re-listing up to `attempts` more times while the listing
    visibly lags the triggering event. Bounded: never more than
    attempts * interval seconds of waiting."""
    for n in range(attempts + 1):
        checks, runs = read_state(gh, repo, sha)
        ev = evaluate(checks, runs, check_name=check_name,
                      ignore_workflows=ignore_workflows)
        if n == attempts or not looks_stale(ev, runs, trigger):
            break
        log(f"listing lags the triggering event; re-listing in {interval:.0f}s "
            f"({n + 1}/{attempts})")
        sleep(interval)
    if ev.only_cancelled_pending:
        cancelled, failed = ev.of("cancelled"), ev.of("failed")
        reason = (f"{len(cancelled)} check(s) cancelled and not re-run: "
                  + ", ".join(i.name for i in cancelled))
        if failed:
            reason = (f"{len(failed)} of {len(ev.items)} check(s) failed; " + reason)
        ev = Evaluation("failure", ev.items, reason[:900])
    return ev


def add_failure_details(gh, repo: str, ev: Evaluation) -> None:
    for item in ev.of("failed"):
        try:
            annotations = gh.paginate(f"repos/{repo}/check-runs/{item.check_id}/annotations")
        except RuntimeError:
            annotations = []
        steps: list[str] = []
        if not failure_detail(annotations, []) and item.app == "github-actions":
            try:   # an Actions job's check run id is its job id
                job = gh.get(f"repos/{repo}/actions/jobs/{item.check_id}") or {}
                steps = [s["name"] for s in job.get("steps") or []
                         if s.get("conclusion") == "failure"]
            except RuntimeError:
                steps = []
        item.detail = failure_detail(annotations, steps)


def publish_check_run(gh, repo: str, sha: str, check_name: str, ev: Evaluation,
                      title: str, summary: str, details_url: str, now: str) -> dict:
    """Create or update the gate's check run.

    An in-progress gate run is updated in place. Once completed it is never
    reopened: a changed state gets a NEW check run, so the newest check run of
    this name on the commit is always the gate's latest verdict.
    """
    existing = gh.paginate(f"repos/{repo}/commits/{sha}/check-runs",
                           {"check_name": check_name, "filter": "all"},
                           key="check_runs")
    mine = [c for c in existing if c.get("external_id") == GATE_EXTERNAL_ID]
    current = max(mine, key=lambda c: c["id"]) if mine else None
    body: dict = {"name": check_name, "details_url": details_url,
                  "external_id": GATE_EXTERNAL_ID,
                  "output": {"title": title, "summary": summary}}
    if ev.verdict == "pending":
        body["status"] = "in_progress"
    else:
        body.update(status="completed", conclusion=ev.verdict, completed_at=now)
    if current is not None and current.get("status") != "completed":
        return gh.patch(f"repos/{repo}/check-runs/{current['id']}", body)
    return gh.post(f"repos/{repo}/check-runs",
                   {**body, "head_sha": sha, "started_at": now})


def _marked(body: str) -> bool:
    return any(body.startswith(m) for m in (COMMENT_MARKER, *LEGACY_COMMENT_MARKERS))


def sync_comment(gh, repo: str, pr: int, ev: Evaluation, body: str, log=print) -> None:
    """Failure: upsert one comment. Success: remove every generation of it.
    Pending: leave whatever is there."""
    if ev.verdict == "pending":
        return
    comments = gh.paginate(f"repos/{repo}/issues/{pr}/comments")
    ours = [c for c in comments if _marked(c.get("body") or "")]
    if ev.verdict == "failure":
        keep = next((c for c in ours if c["body"].startswith(COMMENT_MARKER)),
                    ours[0] if ours else None)
        for c in ours:
            if keep is not None and c["id"] != keep["id"]:
                _delete_comment(gh, repo, c["id"], log)
        if keep is None:
            gh.post(f"repos/{repo}/issues/{pr}/comments", {"body": body})
            log(f"PR #{pr}: posted Validation Summary comment")
        else:
            gh.patch(f"repos/{repo}/issues/comments/{keep['id']}", {"body": body})
            log(f"PR #{pr}: updated Validation Summary comment")
    else:
        for c in ours:
            _delete_comment(gh, repo, c["id"], log)
        if ours:
            log(f"PR #{pr}: removed {len(ours)} earlier Validation Summary comment(s)")


def _delete_comment(gh, repo: str, cid: int, log) -> None:
    try:
        gh.delete(f"repos/{repo}/issues/comments/{cid}")
    except RuntimeError as exc:   # cosmetic; the verdict is the check run
        log(f"::warning::could not delete Validation Summary comment {cid}: {exc}")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append(path: str | None, text: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


# Implements: HHT-OPS-composite-action-library/A
def run(env: dict, gh=None, sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = _now, log=print) -> int:
    repo = env["GITHUB_REPOSITORY"]
    check_name = env.get("INPUT_CHECK_NAME") or "Validation Summary"
    base = env.get("INPUT_BASE_BRANCH") or "main"
    ignore = [w.strip() for w in (env.get("INPUT_IGNORE_WORKFLOWS") or "").splitlines()
              if w.strip()]
    attempts = int(env.get("INPUT_RELIST_ATTEMPTS") or 3)
    interval = float(env.get("INPUT_RELIST_INTERVAL_SECONDS") or 20)
    with open(env["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
        event = json.load(fh)
    trigger, skip = parse_trigger(env.get("GITHUB_EVENT_NAME", ""), event, ignore)
    if trigger is None:
        log(f"Nothing to evaluate: {skip}.")
        return 0
    sha = trigger["sha"]
    gh = gh or GitHub(env["GITHUB_TOKEN"], env.get("GITHUB_API_URL") or "https://api.github.com",
                      sleep=sleep)
    details_url = (f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}"
                   f"/actions/runs/{env.get('GITHUB_RUN_ID', '')}")
    log(f"Triggered by {trigger['kind']} {trigger.get('action')} of "
        f"{trigger.get('name')!r} on {sha[:7]}")

    prs = open_prs_for(gh, repo, sha, base)
    if not prs:
        log(f"{sha[:7]} is not the head of an open pull request into {base}; nothing to do.")
        return 0

    try:
        ev = evaluate_with_relist(gh, repo, sha, trigger, check_name=check_name,
                                  ignore_workflows=ignore, attempts=attempts,
                                  interval=interval, sleep=sleep, log=log)
        if ev.verdict == "failure":
            add_failure_details(gh, repo, ev)
    except RuntimeError as exc:
        # Fail closed and say so: a gate that cannot read the commit's checks
        # must not leave an earlier pass standing as the newest verdict.
        log(f"::error::Validation Summary could not evaluate {sha[:7]}: {exc}")
        ev = Evaluation("failure", [], "gate evaluation error -- re-run the "
                        "'Validation Summary Gate' workflow run")
        publish_check_run(gh, repo, sha, check_name, ev, ev.reason,
                          f"## Validation Summary: could not evaluate\n\n`{exc}`",
                          details_url, now())
        return 1

    title, summary = render(ev, sha)
    stamp = now()
    publish_check_run(gh, repo, sha, check_name, ev, title, summary, details_url, stamp)
    for pr in prs:
        sync_comment(gh, repo, pr, ev, comment_body(summary, details_url, stamp), log=log)
    log(f"Validation Summary on {sha[:7]}: {ev.verdict} -- {ev.reason}")
    _append(env.get("GITHUB_STEP_SUMMARY"), summary)
    _append(env.get("GITHUB_OUTPUT"), f"verdict={ev.verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(run(dict(os.environ)))
