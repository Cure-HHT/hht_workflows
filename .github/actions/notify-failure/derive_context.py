#!/usr/bin/env python3
"""Derive failure context for the notify-failure composite.

Reads the CURRENT run's jobs from the GitHub API, identifies every job that
did not succeed and (where available) the first step within it that failed,
and composes the Slack message body. It also decides HOW the announcement is
delivered — a channel post (push/schedule, plus dispatch runs whose triggerer
we can't resolve to an email) or a DM to the triggerer (workflow_dispatch when
the actor-email cascade resolves) — emitting `mode` and `dm-email` for the
composite to act on.

Implements: HHT-OPS-failure-notification-routing/A
"""
import json
import os
import subprocess
import sys
import uuid

# Job conclusions that mean "this run did not succeed and should be announced".
FAILED_CONCLUSIONS = ("failure", "timed_out", "cancelled")


def failed_units(jobs):
    """[(job_name, failed_step_name_or_None, conclusion)] in definition order.

    A job with no failed step (timeout, runner death, cancellation) yields
    None for the step — there is no step to name.
    """
    units = []
    for job in jobs:
        conclusion = job.get("conclusion")
        if conclusion not in FAILED_CONCLUSIONS:
            continue  # success, skipped, or still running (the notify job itself)
        step_name = None
        for step in job.get("steps") or []:
            if step.get("conclusion") == "failure":
                step_name = step.get("name")
                break
        units.append((job.get("name"), step_name, conclusion))
    return units


def _parse_hints(hints):
    """Hints are advisory: malformed JSON must never break the announcement."""
    if not hints:
        return {}
    try:
        parsed = json.loads(hints)
    except (ValueError, TypeError):
        print("::warning::notify-failure: `hints` is not valid JSON; ignoring.")
        return {}
    if not isinstance(parsed, dict):
        print("::warning::notify-failure: `hints` is not a JSON object; ignoring.")
        return {}
    return parsed


def compose(workflow, branch, actor, run_url, units, hints):
    hint_map = _parse_hints(hints)
    lines = [f":x: *{workflow} failed on {branch}*", ""]
    for job_name, step_name, conclusion in units:
        if step_name is None:
            lines.append(f"*Failed:* {job_name} ({conclusion}, no failed step)")
        else:
            lines.append(f"*Failed:* {job_name} / {step_name}")
            hint = hint_map.get(step_name)
            if hint:
                lines.append(f"*Hint:* {hint}")
    if not units:
        lines.append("*Failed:* (no failed job identified — see the run)")
    lines += ["", f"*Triggered by:* @{actor}", "", run_url]
    return "\n".join(lines)


def committer_email(event_name, event):
    """Only a push has a committer to notify; a scheduled run has none."""
    if event_name != "push":
        return ""
    return (((event or {}).get("head_commit") or {}).get("author") or {}).get("email", "")


# A GitHub privacy no-reply address (e.g. `12345+user@users.noreply.github.com`
# or `user@users.noreply.github.com`). Real from the git/GitHub side, but no
# Slack user has it, so it is useless for a users.lookupByEmail DM.
#
# GitHub's ONLY no-reply host is `users.noreply.github.com` — matched by
# exact equality on the part after the last "@", not by suffix. A suffix
# check (`endswith("noreply.github.com")`) would also reject a lookalike
# host like `evilnoreply.github.com` or `x.attacker.com.noreply.github.com`
# under attacker control; exact-host match cannot be spoofed that way.
_GITHUB_NOREPLY_HOST = "users.noreply.github.com"


def _is_github_noreply(email):
    return email.rpartition("@")[2].lower() == _GITHUB_NOREPLY_HOST


def resolve_actor_email(login, repo, fetch):
    """Best-effort GitHub login -> email for a workflow_dispatch triggerer.

    GitHub Actions never exposes the triggering actor's email, and this org
    has NO SAML SSO to query, so cascade over public signals:

      1. the actor's public profile email — `GET /users/{login}` `.email`
         (often null);
      2. failing that, the author email on the actor's most recent commit —
         `GET /repos/{repo}/commits?author={login}&per_page=1`
         `[0].commit.author.email` — rejecting any `*.noreply.github.com`
         privacy address (real, but no Slack user has it);
      3. failing both, "" (unresolved) — the caller then falls back to a
         channel post that still names the actor.

    `fetch` is a callable taking a `gh api` path and returning parsed JSON (or
    None on any failure). Injected so the cascade is unit-testable with a fake,
    mirroring how `_fetch_jobs` is structured.
    """
    if not login:
        return ""

    profile = fetch(f"users/{login}")
    if isinstance(profile, dict):
        email = (profile.get("email") or "").strip()
        if email:
            return email

    commits = fetch(f"repos/{repo}/commits?author={login}&per_page=1")
    if isinstance(commits, list) and commits and isinstance(commits[0], dict):
        author = ((commits[0].get("commit") or {}).get("author") or {})
        email = (author.get("email") or "").strip()
        if email and not _is_github_noreply(email):
            return email

    return ""


def delivery(event_name, event, actor, repo, fetch):
    """Decide HOW to deliver: return (mode, dm_email).

    - push / schedule -> `channel`, DM the committer (email may be "" for a
      scheduled run, which has no committer). Channel post + committer DM,
      exactly as before.
    - workflow_dispatch, actor email resolved -> `dm-only`, DM the triggerer;
      no channel post.
    - workflow_dispatch, unresolved -> `channel`, no DM. The channel post
      falls to the default workflow-failure route, and the message text still
      names the actor (`*Triggered by:* @<actor>`) so a human can tell who
      triggered it.
    """
    if event_name == "workflow_dispatch":
        email = resolve_actor_email(actor, repo, fetch)
        if email:
            return "dm-only", email
        return "channel", ""
    return "channel", committer_email(event_name, event)


def _gh_api_json(path):
    """`gh api <path>` -> parsed JSON, or None on any failure.

    Best-effort by design: the actor-email cascade is advisory (it only
    decides whether a DM is possible), so a 404 for a login with no public
    profile, a rate-limit, or a parse error must degrade to "unresolved",
    never abort the announcement.
    """
    try:
        out = subprocess.run(
            ["gh", "api", path],
            capture_output=True, text=True, check=True, timeout=30).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, OSError, ValueError):
        # SubprocessError covers CalledProcessError (nonzero exit) and
        # TimeoutExpired; OSError covers a missing `gh` binary
        # (FileNotFoundError) on a misconfigured self-hosted runner. None of
        # these may propagate — this fetch backs an advisory cascade only.
        return None


def _fetch_jobs(repo, run_id):
    """Every job of the run, across all pages.

    `gh api --paginate` concatenates each page's body with NO separator and
    no trailing newline, so the raw output of a 2+ page response is not
    line-delimited JSON and cannot be parsed page-by-page. `--jq '.jobs[]'`
    makes gh do the framing for us: one compact JSON object per line,
    uniformly across every page. `per_page=100` also keeps the common case
    (well under 100 jobs) to a single request.
    """
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100",
         "--paginate", "--jq", ".jobs[]"],
        capture_output=True, text=True, check=True, timeout=30).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["GITHUB_RUN_ID"]
    workflow = os.environ.get("GITHUB_WORKFLOW", "workflow")
    branch = os.environ.get("GITHUB_REF_NAME", "unknown")
    actor = os.environ.get("GITHUB_ACTOR", "unknown")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    hints = os.environ.get("INPUT_HINTS", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}"

    try:
        jobs = _fetch_jobs(repo, run_id)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        # Degraded but still announced: a context-lookup failure must not
        # swallow the failure notification itself — including a missing `gh`
        # binary (FileNotFoundError/OSError) or a hung `gh api` call
        # (subprocess.TimeoutExpired, a SubprocessError subclass) on a
        # misconfigured self-hosted runner. CalledProcessError.__str__
        # reports only the return code, so include stderr — otherwise a 403
        # from a missing `actions: read` grant is indistinguishable from a
        # parse failure.
        detail = getattr(exc, "stderr", "") or ""
        print(f"::warning::notify-failure: could not read run jobs ({exc}"
              f"{': ' + detail.strip() if detail.strip() else ''}); "
              "posting a degraded message.")
        jobs = []

    units = failed_units(jobs)
    text = compose(workflow, branch, actor, run_url, units, hints)

    # The delivery decision is advisory (it only chooses WHO gets a DM and
    # whether a channel post happens). An unreadable or malformed event
    # payload must never be able to abort this script and thereby suppress the
    # announcement it exists to send.
    event = {}
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path:
        try:
            with open(event_path, encoding="utf-8") as handle:
                event = json.load(handle)
        except (OSError, ValueError) as exc:
            print(f"::warning::notify-failure: could not read the event payload "
                  f"({exc}); continuing without a committer email.")

    mode, dm_email = delivery(event_name, event, actor, repo, _gh_api_json)

    # Per-invocation delimiter: the wrapped value contains the branch name,
    # step names, and caller-supplied hint text, any of which could legally
    # contain a fixed literal and so truncate the output / inject outputs.
    delim = f"__NF_EOF_{uuid.uuid4().hex}__"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write(f"text<<{delim}\n")
        out.write(text + "\n")
        out.write(f"{delim}\n")
        out.write(f"dm-email={dm_email}\n")
        out.write(f"mode={mode}\n")


if __name__ == "__main__":
    sys.exit(main())
