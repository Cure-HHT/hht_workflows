#!/usr/bin/env python3
"""Derive failure context for the notify-failure composite.

Reads the CURRENT run's jobs from the GitHub API, identifies every job that
did not succeed and (where available) the first step within it that failed,
and composes the Slack message body.

Implements: HHT-OPS-failure-notification-routing/A
"""
import json
import os
import subprocess
import sys

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


def _fetch_jobs(repo, run_id):
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/actions/runs/{run_id}/jobs", "--paginate"],
        capture_output=True, text=True, check=True).stdout
    jobs = []
    for chunk in out.strip().splitlines():
        if not chunk.strip():
            continue
        jobs.extend(json.loads(chunk).get("jobs", []))
    return jobs


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
    except (subprocess.CalledProcessError, ValueError) as exc:
        # Degraded but still announced: a context-lookup failure must not
        # swallow the failure notification itself.
        print(f"::warning::notify-failure: could not read run jobs ({exc}); "
              "posting a degraded message.")
        jobs = []

    units = failed_units(jobs)
    text = compose(workflow, branch, actor, run_url, units, hints)

    event = {}
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        with open(event_path, encoding="utf-8") as handle:
            event = json.load(handle)

    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write("text<<__NF_EOF__\n")
        out.write(text + "\n")
        out.write("__NF_EOF__\n")
        out.write(f"committer-email={committer_email(event_name, event)}\n")


if __name__ == "__main__":
    sys.exit(main())
