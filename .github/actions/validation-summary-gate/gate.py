#!/usr/bin/env python3
"""Validation Summary gate -- event-driven evaluation.

One evaluation of the "Validation Summary" required check for one commit.
The caller is a workflow triggered by `workflow_run` (every workflow
starting or finishing, whatever event raised it) and by
`check_run: completed` (check runs posted by GitHub Apps other than
GitHub Actions). Each firing reads the commit's check runs and workflow
runs ONCE, decides, and publishes the verdict as a COMMIT STATUS with
context "Validation Summary". Nothing waits on a runner: the next
completion is the next evaluation.

Why a commit status and not a check run: GitHub counts checks created by
workflow jobs toward a ruleset only when the run was triggered by push,
pull_request, pull_request_review, pull_request_target, deployment or
deployment_status ("Troubleshooting required status checks"), and
workflow_run is not on that list. Commit statuses carry no such
restriction, and a required context is satisfied by either kind -- when
both exist under one name, both must pass.

Semantics carried over from the polling gate it replaces
(.github/actions/validation-summary): every check run on the head commit
counts except those of the gate's own workflow; the newest check run of each job
wins; skipped and neutral are passing; cancelled means "waiting for a
re-run"; the gate fails, and upserts one PR comment naming the failed
checks with their annotations, once every check has completed and any
failed. Commit statuses are not read at all, as before, so the gate's own
status can never feed back into its verdict. Differences, each fail-closed:

- timed_out, action_required, startup_failure, stale and any unknown
  conclusion count as failed. The polling gate counted only `failure`.
- "Newest of each name" is decided per workflow: two workflows that both
  have a job called `check` are two checks, not one.
- A workflow run still queued, in progress, waiting, or awaiting approval
  is pending even before its jobs have created check runs.
- A workflow run that ended badly (startup_failure, failure, timed_out --
  e.g. a YAML error that never created a job) is a failure even with no
  check runs; one cancelled with no check runs is a cancelled item.
- A cancelled check or run with no re-run anywhere in sight is reported as
  a failure after a bounded re-read instead of being waited on until a
  timeout. The polling gate reached the same verdict after its budget.

Names a pull request controls do not exempt a check. Workflow display names
and check-run names come from the pull request's own workflow files, so the
gate never ignores anything by name: its own runs are recognised by the
workflow file path together with a non-pull-request event (a same-repo
branch push raises `push` at that path, but such a run belongs to the
branch, not to a pull request's head, and only drops its own content), and
the polling job's "Validation Summary" check run, while it exists, is
counted like any other check. A workflow that takes the gate's own
workflow name is a failure, since it reads as the gate in every listing.

What the gate does not stop: the required "Validation Summary" context is a
commit status, and GitHub accepts it from any workflow in the repository
that holds `statuses: write`. A same-repo pull request can add such a
workflow, keep it running until every other check has finished, and post
`success` itself; no later event re-evaluates. The polling job it replaces
was open to the same attack, since a pull request could edit it. Closing
it needs the status posted by a dedicated GitHub App and the required check
pinned to that App's `integration_id`, which is a follow-up; until then,
review of `.github/workflows/` changes is what guards it.

Runs of the `dynamic` event (GitHub's Copilot code-review agent) are not
counted: they are triggered by a review request, not by the pull request
event, they validate nothing, and no event is documented to fire when they
finish, so waiting on one could leave the gate pending for good.
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

# The current PR-comment marker (pr-comment-upsert convention), then the two
# earlier generations. A failure upserts the current one; a pass removes all.
# Only comments written by this identity are ever touched.
COMMENT_MARKER = "<!-- pr-comment-upsert:validation-summary -->"
LEGACY_COMMENT_MARKERS = ("<!-- validation-summary -->", "<!-- ci-gate-summary -->")
# The login whose comments the gate owns: GITHUB_TOKEN posts as this bot.
# A different token posts under another login; set the `comment-author`
# input to it, or every failure adds a new comment beside the old one.
DEFAULT_COMMENT_AUTHOR = "github-actions[bot]"

OK_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
FAILED_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "action_required", "startup_failure", "stale"})
# Runs that can never be a pull request's verdict: the Copilot review agent
# (`dynamic`) and scheduled runs, which run on the default branch's head. Push
# runs of the default branch are excluded as well (see `out_of_scope`). The
# wrapper's job `if:` skips the same runs, so no runner starts for them; the
# evaluation ignores them too, or a run that can never fire the gate would
# hold its verdict.
IGNORED_RUN_EVENTS = frozenset({"dynamic", "schedule"})
PR_EVENTS = frozenset({"pull_request", "pull_request_target"})
DEFAULT_GATE_WORKFLOW_PATH = ".github/workflows/validation-summary-gate.yml"
DEFAULT_GATE_WORKFLOW_NAME = "Validation Summary Gate"

# Annotation lines that say nothing beyond "it failed".
_NOISE = re.compile(
    r"Process completed with exit code|^Unexpected failure|^Failed during:")

SUMMARY_LIMIT = 60000       # PR comment bodies are capped at 65536.
DESCRIPTION_LIMIT = 140     # commit status descriptions longer than this are refused

RERUN_HINT = "if stuck, re-run the Validation Summary Gate workflow"
RERUN_GUIDANCE = (
    "If this stays pending after every check above has finished, the event "
    "that should have re-evaluated it did not arrive (GitHub does not fire "
    "`check_run` for a check suite whose head SHA is associated with GitHub "
    "Actions, and listings can lag). Re-run the latest **Validation Summary "
    "Gate** workflow run from the Actions tab; it re-reads every check.")


# --------------------------------------------------------------------------
# Evaluation (pure)
# --------------------------------------------------------------------------

# Implements: HHT-OPS-composite-action-library/A
def safe(text) -> str:
    """Neutralise text a pull request controls (workflow, job and check names,
    annotation messages) before it reaches a log line, a commit status or a
    PR comment: no line break can start a `::workflow-command::`, no `::`
    survives to form one, and no `@` mentions anyone."""
    text = re.sub(r"[\r\n]+", " ", str(text))
    return text.replace("::", ":\u200b:").replace("@", "@\u200b")


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
    def only_cancelled_pending(self) -> bool:
        return (self.verdict == "pending" and not self.of("pending")
                and bool(self.of("cancelled")))

    @property
    def external_pending(self) -> bool:
        return any(i.state == "pending" and i.check_id is not None
                   and i.app not in ("", "github-actions") for i in self.items)


def _run_key(run: dict) -> tuple:
    return (run.get("workflow_id") or run.get("name"), run.get("event"))


def latest_runs(workflow_runs: Iterable[dict]) -> list[dict]:
    """Newest run of each (workflow, event) on the commit."""
    best: dict[tuple, dict] = {}
    for run in workflow_runs:
        key = _run_key(run)
        cur = best.get(key)
        if cur is None or run["id"] > cur["id"]:
            best[key] = run
    return list(best.values())


# Implements: HHT-OPS-composite-action-library/A
def latest_per_job(check_runs: Iterable[dict], workflow_runs: Iterable[dict]) -> list[tuple]:
    """Newest check run of each (workflow, name), as (check_run, workflow_name).

    The workflow is found through the check run's suite. Deduplicating by name
    alone would let workflow A's passing `check` hide workflow B's failing
    `check`. A check whose suite belongs to no listed workflow run (another
    GitHub App's) is keyed by its suite. Newest is decided by id (ids increase
    with creation), not by API order.
    """
    suite_to_run = {r.get("check_suite_id"): r for r in workflow_runs
                    if r.get("check_suite_id") is not None}
    best: dict[tuple, tuple] = {}
    for cr in check_runs:
        suite = (cr.get("check_suite") or {}).get("id")
        run = suite_to_run.get(suite)
        group = ("workflow",) + _run_key(run) if run else ("suite", suite)
        key = (group, cr["name"])
        cur = best.get(key)
        if cur is None or cr["id"] > cur[0]["id"]:
            best[key] = (cr, (run or {}).get("name") or "")
    return sorted(best.values(), key=lambda t: (t[0]["name"], t[1]))


# Implements: HHT-OPS-composite-action-library/A
def out_of_scope(run: dict, default_branch: str = "") -> bool:
    """A run that is never part of a pull request's verdict: an ignored
    event, or a push to the default branch (the merged commit, not a pull
    request's head). Branch pushes stay in scope: a same-repository pull
    request's head is pushed to its branch."""
    if run.get("event") in IGNORED_RUN_EVENTS:
        return True
    return bool(default_branch) and run.get("event") == "push" and \
        run.get("head_branch") == default_branch


def is_gate_run(run: dict, gate_path: str) -> bool:
    """A run of the gate's own workflow: its file path, and an event other
    than a pull request's. A pull request can rename any workflow and can add
    a `pull_request` trigger to the gate's file, and those runs are counted.
    A same-repository branch push to the gate's file does raise `push` and is
    ignored here, but a push run belongs to the branch, not to the pull
    request: ignoring it drops nothing the pull request is judged on, and the
    pull request's own runs of that file are still counted."""
    return run.get("path") == gate_path and run.get("event") not in PR_EVENTS


# Implements: HHT-OPS-composite-action-library/A
def evaluate(check_runs: list[dict], workflow_runs: list[dict], *,
             gate_path: str = DEFAULT_GATE_WORKFLOW_PATH,
             gate_name: str = DEFAULT_GATE_WORKFLOW_NAME,
             default_branch: str = "") -> Evaluation:
    def ignored(run: dict) -> bool:
        return is_gate_run(run, gate_path) or out_of_scope(run, default_branch)

    ignored_suites = {r.get("check_suite_id") for r in workflow_runs if ignored(r)} - {None}
    relevant = [
        cr for cr in check_runs
        if (cr.get("check_suite") or {}).get("id") not in ignored_suites
    ]
    jobs = latest_per_job(relevant, workflow_runs)
    name_count: dict[str, int] = {}
    for cr, _ in jobs:
        name_count[cr["name"]] = name_count.get(cr["name"], 0) + 1

    items: list[Item] = []
    for cr, wf_name in jobs:
        status, conclusion = cr.get("status"), cr.get("conclusion")
        name = safe(cr["name"])
        if name_count[cr["name"]] > 1 and wf_name:
            name = f"{safe(wf_name)} / {name}"
        item = Item(name=name, state="ok", status="",
                    url=cr.get("html_url") or "", check_id=cr["id"],
                    app=((cr.get("app") or {}).get("slug") or ""),
                    suite_id=(cr.get("check_suite") or {}).get("id"))
        if status != "completed":
            item.state, item.status = "pending", status or "queued"
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

    by_suite: dict = {}
    for i in items:
        by_suite.setdefault(i.suite_id, set()).add(i.state)
    for run in latest_runs(workflow_runs):
        if ignored(run):
            continue
        status, conclusion = run.get("status"), run.get("conclusion")
        suite_states = by_suite.get(run.get("check_suite_id"), set())
        base = Item(name=f"workflow: {safe(run.get('name'))}", state="pending", status="",
                    url=run.get("html_url") or "", suite_id=run.get("check_suite_id"))
        if run.get("name") == gate_name:
            # Only the gate's own file is skipped, by path, so a workflow
            # wearing the gate's name does fire an evaluation. It still fails:
            # a second "Validation Summary Gate" in the run list makes the
            # gate's own runs indistinguishable to a reader of the checks.
            base.state, base.status = "failed", "Named like the gate"
            base.detail = (f"a workflow named {gate_name!r} cannot trigger the gate "
                           f"when it finishes; rename it")
            items.append(base)
            continue
        if status != "completed":
            if "pending" in suite_states:
                continue    # already listed through its pending check runs
            base.status = status or "queued"
        elif conclusion == "action_required":
            base.status = "awaiting approval"
        elif conclusion in OK_CONCLUSIONS:
            continue
        elif conclusion == "cancelled":
            if suite_states & {"cancelled", "pending", "failed"}:
                continue    # its own check runs already say so
            base.state, base.status = "cancelled", "Run cancelled, awaiting re-run"
        else:
            # failure / timed_out / startup_failure / stale / unknown. A run that
            # never created a job (a YAML error) has no check run to fail.
            if "failed" in suite_states:
                continue
            base.state, base.status = "failed", f"Run {conclusion}"
            base.detail = ("workflow run ended without a failing job "
                           "(e.g. invalid workflow file)")
        items.append(base)

    pending = [i for i in items if i.state in ("pending", "cancelled")]
    failed = [i for i in items if i.state == "failed"]
    if pending:
        return Evaluation("pending", items,
                          f"waiting on {len(pending)} check(s)")
    if not [i for i in items if i.check_id is not None] and not failed:
        return Evaluation("pending", items, "no check runs reported yet")
    if failed:
        return Evaluation("failure", items,
                          f"{len(failed)} of {len(items)} check(s) failed")
    return Evaluation("success", items,
                      f"all {len(items)} check(s) passed (or were skipped)")


# Implements: HHT-OPS-composite-action-library/A
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
        # A listing still showing an earlier attempt of a re-run lags the
        # event: its conclusion is the previous attempt's, not this one's.
        attempt = trigger.get("run_attempt")
        if isinstance(attempt, int) and (run.get("run_attempt") or 0) < attempt:
            return True
        if trigger.get("action") == "completed":
            if run.get("status") != "completed":
                return True
            if any(i.suite_id == trigger.get("suite_id") and i.check_id is not None
                   for i in ev.of("pending")):
                return True
    elif trigger.get("kind") == "check_run":
        cid = trigger.get("check_id")
        tname = safe(trigger.get("name"))

        def newer_run_of_trigger(i: Item) -> bool:
            # The same check posted again: same app and exactly the same
            # name (or that name under its workflow, when names collide). A
            # name that merely ends the same way is a different check.
            return (isinstance(cid, int) and i.check_id > cid
                    and i.app == trigger.get("app", "")
                    and (i.name == tname or i.name.endswith(" / " + tname)))

        listed = [i for i in ev.items if i.check_id is not None
                  and (i.check_id == cid or newer_run_of_trigger(i))]
        if not listed:
            return True     # not listed yet, and no newer run of it either
        if trigger.get("action") == "completed" and any(
                i.check_id == cid for i in ev.of("pending")):
            return True
        # `created`: the check run is expected to be pending; that is the
        # point of evaluating it (an earlier pass must not stand meanwhile).
    completed_suites = {r.get("check_suite_id") for r in workflow_runs
                        if r.get("status") == "completed"}
    return any(i.check_id is not None and i.suite_id in completed_suites
               for i in ev.of("pending"))


# --------------------------------------------------------------------------
# Rendering (pure)
# --------------------------------------------------------------------------

def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def describe(ev: Evaluation, stuck_hint: bool = False) -> str:
    """The commit-status description: <= 140 characters."""
    if ev.verdict == "pending":
        waiting = [i.name for i in ev.items if i.state in ("pending", "cancelled")]
        text = "Waiting for: " + (", ".join(waiting) if waiting else ev.reason)
        if stuck_hint:
            hint = f" ({RERUN_HINT})"
            return _truncate(text, DESCRIPTION_LIMIT - len(hint)) + hint
        return _truncate(text, DESCRIPTION_LIMIT)
    if ev.verdict == "failure":
        names = [i.name for i in ev.of("failed")] or [i.name for i in ev.of("cancelled")]
        return _truncate(f"{ev.reason}: {', '.join(names)}" if names and ":" not in ev.reason
                         else ev.reason, DESCRIPTION_LIMIT)
    return _truncate(ev.reason, DESCRIPTION_LIMIT)


def render(ev: Evaluation, sha: str, stuck_hint: bool = False) -> tuple[str, str]:
    """(title, markdown summary) for the step summary and the PR comment.
    The table matches the polling gate's comment."""
    failed = ev.of("failed")
    if ev.verdict == "failure":
        cancelled = ev.of("cancelled")
        head = (f"## Validation Summary: {len(failed)} of {len(ev.items)} "
                f"check(s) failed")
        if cancelled and not failed:
            head = (f"## Validation Summary: {len(cancelled)} check(s) "
                    f"cancelled and not re-run")
    elif ev.verdict == "pending":
        waiting = [i for i in ev.items if i.state in ("pending", "cancelled")]
        head = f"## Validation Summary: waiting on {len(waiting)} check(s)"
        if failed:
            head += f" ({len(failed)} already failed)"
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
    parts = [head, "", f"Commit `{sha[:7]}`", "",
             "| Check | Status | Details |",
             "|-------|--------|---------|",
             *rows]
    if ev.verdict == "pending" and stuck_hint:
        parts += ["", RERUN_GUIDANCE]
    body = "\n".join(parts)
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
            line = safe(line)
            if line and not _NOISE.search(line) and line not in msgs:
                msgs.append(line)
    if msgs:
        return "; ".join(msgs[:3])
    if failed_steps:
        return "Failed step(s): " + ", ".join(safe(n) for n in failed_steps)
    return ""




# --------------------------------------------------------------------------
# Trigger parsing
# --------------------------------------------------------------------------

# Implements: HHT-OPS-composite-action-library/A
def parse_trigger(event_name: str, event: dict,
                  gate_path: str = DEFAULT_GATE_WORKFLOW_PATH):
    """Return (trigger dict, None) or (None, reason-to-skip).

    Every workflow run is a trigger, whatever its event: a run raised by a
    push, a review, a label, a re-run or a manual dispatch on a pull
    request's head commit is counted by the evaluation, so its start and its
    end must each fire one, or a pass posted before it finished could stand.
    Whether the commit is an open pull request's head is decided afterwards,
    from the API. Only the gate's own runs are skipped."""
    if event_name == "workflow_run":
        run = event.get("workflow_run") or {}
        if is_gate_run(run, gate_path):
            return None, "triggering run is the gate's own workflow"
        default_branch = (event.get("repository") or {}).get("default_branch") or ""
        if out_of_scope(run, default_branch):
            return None, (f"a {safe(run.get('event'))} run of "
                          f"{safe(run.get('head_branch'))} is never a pull request's verdict")
        trig = {"kind": "workflow_run", "sha": run.get("head_sha") or "",
                "run_id": run.get("id"), "suite_id": run.get("check_suite_id"),
                "run_attempt": run.get("run_attempt"),
                "name": run.get("name"), "action": event.get("action")}
    elif event_name == "check_run":
        cr = event.get("check_run") or {}
        if ((cr.get("app") or {}).get("slug")) == "github-actions":
            return None, "check run was created by GitHub Actions"
        trig = {"kind": "check_run", "sha": cr.get("head_sha") or "",
                "check_id": cr.get("id"),
                "suite_id": (cr.get("check_suite") or {}).get("id"),
                "app": (cr.get("app") or {}).get("slug") or "",
                "name": cr.get("name"), "action": event.get("action")}
    else:
        return None, f"unsupported event {event_name!r}"
    if not SHA_RE.match(str(trig["sha"])):
        return None, f"head sha {safe(trig['sha'])!r} is not a commit sha"
    return trig, None


# --------------------------------------------------------------------------
# GitHub REST client
# --------------------------------------------------------------------------

# The job's own budget is 5 minutes; waiting on rate limits must leave room
# for the evaluation and the error status after it.
RATE_LIMIT_WAIT_BUDGET = 120.0


# Implements: HHT-OPS-composite-action-library/A
def retry_delay(code: int, headers, attempt: int, now: float) -> float | None:
    """Seconds to wait before retrying a failed request, or None to give up.

    - 5xx: exponential back-off.
    - 403/429 with `retry-after` (GitHub's secondary rate limit): that many
      seconds.
    - 403/429 with `x-ratelimit-remaining: 0` (the primary limit): until
      `x-ratelimit-reset`.
    - 429 without either header: exponential back-off.
    - any other 403: not a rate limit; give up.
    """
    backoff = float(min(60, 5 * 2 ** attempt))
    if code >= 500:
        return backoff
    if code not in (403, 429):
        return None
    retry_after = headers.get("retry-after")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return backoff
    if headers.get("x-ratelimit-remaining") == "0":
        try:
            return max(0.0, float(headers.get("x-ratelimit-reset")) - now)
        except (TypeError, ValueError):
            return backoff
    return backoff if code == 429 else None


class GitHub:
    def __init__(self, token: str, api: str = "https://api.github.com",
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time,
                 wait_budget: float = RATE_LIMIT_WAIT_BUDGET):
        self.token, self.api, self.sleep = token, api.rstrip("/"), sleep
        self.clock, self.wait_left = clock, wait_budget

    def _wait(self, delay: float, what: str) -> None:
        """Sleep `delay` seconds out of what is left of the budget, or raise
        when it does not fit, so the job still has time to post `error`."""
        if delay > self.wait_left:
            raise RuntimeError(f"{what}; retrying needs {delay:.0f}s, "
                               f"{self.wait_left:.0f}s of the wait budget left")
        self.wait_left -= delay
        self.sleep(delay)

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
                delay = retry_delay(exc.code, exc.headers, attempt, self.clock())
                what = f"{method} {url} -> HTTP {exc.code}"
                if delay is None or attempt == 3:
                    detail = exc.read().decode(errors="replace")[:300]
                    raise RuntimeError(f"{what}: {detail}") from exc
                self._wait(delay, what)
            except urllib.error.URLError as exc:
                if attempt == 3:
                    raise RuntimeError(f"{method} {url} -> {exc.reason}") from exc
                self._wait(float(min(60, 5 * 2 ** attempt)), f"{method} {url} -> {exc.reason}")
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

# Implements: HHT-OPS-composite-action-library/A
def open_prs_for(gh, repo: str, sha: str, base: str = "") -> list[int]:
    """Open PRs whose CURRENT head is `sha`, into any branch, or only into
    `base` when one is given. Every base by default: a stacked pull request
    is gated while it targets another branch, so when its base pull request
    merges and GitHub retargets it, the status it already carries is a real
    evaluation rather than nothing.

    Matched on the base repository's PR list rather than the event's
    `pull_requests` array, which is empty for pull requests from forks.
    """
    params = {"state": "open", **({"base": base} if base else {})}
    prs = gh.paginate(f"repos/{repo}/pulls", params)
    return sorted(p["number"] for p in prs if (p.get("head") or {}).get("sha") == sha)


# Implements: HHT-OPS-composite-action-library/A
def read_state(gh, repo: str, sha: str) -> tuple[list[dict], list[dict]]:
    # filter=all: the default (`latest`) keeps one check run per name, which
    # would hide one of two workflows' same-named jobs before the per-workflow
    # dedupe in latest_per_job ever sees it.
    checks = gh.paginate(f"repos/{repo}/commits/{sha}/check-runs", {"filter": "all"},
                         key="check_runs")
    runs = gh.paginate(f"repos/{repo}/actions/runs", {"head_sha": sha},
                       key="workflow_runs")
    return checks, runs


# Implements: HHT-OPS-composite-action-library/A
def evaluate_with_relist(gh, repo: str, sha: str, trigger: dict, *,
                         gate_path: str, gate_name: str,
                         attempts: int, interval: float,
                         sleep: Callable[[float], None], log=print,
                         default_branch: str = ""):
    """Evaluate, re-listing up to `attempts` more times while the listing
    visibly lags the triggering event. Bounded: never more than
    attempts * interval seconds of waiting.

    Returns (evaluation, stuck): `stuck` is True when the result is pending
    and nothing guarantees another event will re-evaluate it -- the re-reads
    ran out while the listing still lagged, or what remains pending is
    another app's check run.
    """
    stale = False
    for n in range(attempts + 1):
        checks, runs = read_state(gh, repo, sha)
        ev = evaluate(checks, runs, gate_path=gate_path, gate_name=gate_name,
                      default_branch=default_branch)
        stale = looks_stale(ev, runs, trigger)
        if n == attempts or not stale:
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
        return Evaluation("failure", ev.items, reason[:900]), False
    if stale and ev.verdict == "success":
        # The run that fired this evaluation is still missing or unfinished
        # in the listing after every re-read. Passing now would pass without
        # it; wait instead, and say how to unstick it.
        ev = Evaluation("pending", ev.items,
                        "the triggering run is not listed as finished yet")
    stuck = ev.verdict == "pending" and (stale or ev.external_pending)
    return ev, stuck


def add_failure_details(gh, repo: str, ev: Evaluation) -> None:
    for item in ev.of("failed"):
        if item.check_id is None:
            continue    # a workflow run with no jobs has nothing to annotate
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


STATE_FOR_VERDICT = {"pending": "pending", "success": "success",
                     "failure": "failure", "error": "error"}


# Implements: HHT-OPS-composite-action-library/A
def current_state(gh, repo: str, sha: str, context: str) -> str | None:
    """The state of the newest status of `context` on `sha`, or None. The
    commit's statuses are listed newest first; only the first page is read,
    since the newest status of the context is what counts."""
    statuses = gh.get(f"repos/{repo}/commits/{sha}/statuses", {"per_page": 100}) or []
    for st in statuses:
        if st.get("context") == context:
            return st.get("state")
    return None


def publish_status(gh, repo: str, sha: str, context: str, state: str,
                   description: str, target_url: str) -> dict:
    """Set the commit status `context` on `sha`. The newest status of a
    context is the one GitHub uses, so every call simply posts."""
    return gh.post(f"repos/{repo}/statuses/{sha}", {
        "state": STATE_FOR_VERDICT[state],
        "context": context,
        "description": _truncate(description, DESCRIPTION_LIMIT),
        "target_url": target_url,
    })


def _ours(comment: dict, author_login: str = DEFAULT_COMMENT_AUTHOR) -> bool:
    body = comment.get("body") or ""
    author = (comment.get("user") or {}).get("login")
    return author == author_login and any(
        body.startswith(m) for m in (COMMENT_MARKER, *LEGACY_COMMENT_MARKERS))


# Implements: HHT-OPS-composite-action-library/A
def sync_comment(gh, repo: str, pr: int, ev: Evaluation, body: str, log=print,
                 author: str = DEFAULT_COMMENT_AUTHOR) -> None:
    """Failure: upsert one comment. Success: remove every generation of it.
    Pending: leave whatever is there. Only comments this gate's identity
    wrote are touched: anyone can post a comment that starts with a marker."""
    if ev.verdict == "pending":
        return
    comments = gh.paginate(f"repos/{repo}/issues/{pr}/comments")
    ours = [c for c in comments if _ours(c, author)]
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
    except RuntimeError as exc:   # cosmetic; the verdict is the commit status
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


def _event_sha(env: dict) -> str:
    """The head sha the triggering event names, read as defensively as
    possible so even a malformed event or input still identifies the commit
    an `error` status belongs on. Empty when it cannot be determined."""
    try:
        with open(env["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
            event = json.load(fh)
        body = event.get("workflow_run") or event.get("check_run") or {}
        sha = str(body.get("head_sha") or "")
    except Exception:  # noqa: BLE001 -- best effort; the caller fails closed
        return ""
    return sha if SHA_RE.match(sha) else ""


def _details_url(env: dict) -> str:
    return (f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{env.get('GITHUB_REPOSITORY', '')}/actions/runs/{env.get('GITHUB_RUN_ID', '')}")


def _client(env: dict, gh, sleep):
    return gh or GitHub(env["GITHUB_TOKEN"],
                        env.get("GITHUB_API_URL") or "https://api.github.com", sleep=sleep)


# Implements: HHT-OPS-composite-action-library/A
def run(env: dict, gh=None, sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = _now, log=print) -> int:
    """One evaluation. Every input and the event are parsed inside the
    fail-closed block: anything that goes wrong once the commit is known
    posts `error`, so an earlier pass never stands as the newest verdict."""
    check_name = env.get("INPUT_CHECK_NAME") or "Validation Summary"
    details_url = _details_url(env)
    sha = ""
    try:
        repo = env["GITHUB_REPOSITORY"]
        base = env.get("INPUT_BASE_BRANCH") or ""
        author = env.get("INPUT_COMMENT_AUTHOR") or DEFAULT_COMMENT_AUTHOR
        gate_path = env.get("INPUT_GATE_WORKFLOW_PATH") or DEFAULT_GATE_WORKFLOW_PATH
        gate_name = env.get("INPUT_GATE_WORKFLOW_NAME") or DEFAULT_GATE_WORKFLOW_NAME
        sha = _event_sha(env)
        attempts = int(env.get("INPUT_RELIST_ATTEMPTS") or 3)
        interval = float(env.get("INPUT_RELIST_INTERVAL_SECONDS") or 20)
        if attempts < 0 or interval < 0:
            raise ValueError("relist-attempts and relist-interval-seconds must be >= 0")
        with open(env["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
            event = json.load(fh)
        trigger, skip = parse_trigger(env.get("GITHUB_EVENT_NAME", ""), event, gate_path)
        if trigger is None:
            log(f"Nothing to evaluate: {skip}.")
            return 0
        sha = trigger["sha"]
        default_branch = (event.get("repository") or {}).get("default_branch") or ""
        gh = _client(env, gh, sleep)
        log(f"Triggered by {trigger['kind']} {safe(trigger.get('action'))} of "
            f"{safe(trigger.get('name'))!r} on {sha[:7]}")

        prs = open_prs_for(gh, repo, sha, base)
        if not prs:
            log(f"{sha[:7]} is not the head of an open pull request"
                f"{' into ' + base if base else ''}; nothing to do.")
            return 0
        # Pending first: if this job is killed mid-evaluation (timeout,
        # cancellation, runner loss), the newest verdict is not an earlier pass.
        # When the newest status already reads pending, that already holds, and
        # skipping the write spares the secondary rate limit, which counts
        # writes: a busy push fires dozens of evaluations.
        if current_state(gh, repo, sha, check_name) != "pending":
            publish_status(gh, repo, sha, check_name, "pending",
                           "Evaluating the checks on this commit", details_url)
        ev, stuck = evaluate_with_relist(
            gh, repo, sha, trigger, gate_path=gate_path, gate_name=gate_name,
            attempts=attempts, interval=interval, sleep=sleep, log=log,
            default_branch=default_branch)
        if ev.verdict == "failure":
            add_failure_details(gh, repo, ev)
        title, summary = render(ev, sha, stuck_hint=stuck)
        stamp = now()
        publish_status(gh, repo, sha, check_name, ev.verdict,
                       describe(ev, stuck_hint=stuck), details_url)
        for pr in prs:
            sync_comment(gh, repo, pr, ev, comment_body(summary, details_url, stamp), log=log,
                         author=author)
    except Exception as exc:  # noqa: BLE001 -- fail closed on anything
        log(f"::error::Validation Summary could not evaluate {sha[:7] or 'the commit'}: "
            f"{safe(exc)}")
        _publish_error(env, gh, sleep, sha, check_name,
                       "Gate could not evaluate; re-run the Validation Summary Gate workflow",
                       details_url, log)
        _append(env.get("GITHUB_STEP_SUMMARY"),
                f"## Validation Summary: could not evaluate\n\n`{safe(exc)}`")
        return 1

    log(f"Validation Summary on {sha[:7]}: {ev.verdict} -- {ev.reason}")
    _append(env.get("GITHUB_STEP_SUMMARY"), summary)
    _append(env.get("GITHUB_OUTPUT"), f"verdict={ev.verdict}")
    return 0


def _publish_error(env, gh, sleep, sha, check_name, description, details_url, log) -> None:
    if not sha:
        log("::error::the head commit could not be determined; no status was posted")
        return
    try:
        publish_status(_client(env, gh, sleep), env.get("GITHUB_REPOSITORY", ""), sha,
                       check_name, "error", description, details_url)
    except Exception as exc2:  # noqa: BLE001
        log(f"::error::could not publish the error status either: {safe(exc2)}")


# Implements: HHT-OPS-composite-action-library/A
def report_job_failure(env: dict, gh=None, sleep: Callable[[float], None] = time.sleep,
                       log=print) -> int:
    """The `job-failed` mode, run by the wrapper's `if: failure() || cancelled()`
    step: the evaluation step crashed, timed out or was cancelled, possibly
    before it published anything. Post `error` on the event's head commit
    when it is an open pull request's head (or when that cannot be checked),
    so no earlier pass outlives an evaluation that never finished."""
    check_name = env.get("INPUT_CHECK_NAME") or "Validation Summary"
    sha = _event_sha(env)
    try:
        prs = open_prs_for(_client(env, gh, sleep), env["GITHUB_REPOSITORY"], sha,
                           env.get("INPUT_BASE_BRANCH") or "") if sha else []
        if sha and not prs:
            log(f"{sha[:7]} is not the head of an open pull request; nothing to do.")
            return 0
    except Exception as exc:  # noqa: BLE001 -- cannot tell: fail closed
        log(f"::warning::could not list pull requests ({safe(exc)}); posting error anyway")
    _publish_error(env, gh, sleep, sha, check_name,
                   "Gate run failed or was cancelled; re-run the Validation Summary "
                   "Gate workflow", _details_url(env), log)
    return 0


if __name__ == "__main__":
    _env = dict(os.environ)
    if _env.get("INPUT_MODE") == "job-failed":
        sys.exit(report_job_failure(_env))
    sys.exit(run(_env))
