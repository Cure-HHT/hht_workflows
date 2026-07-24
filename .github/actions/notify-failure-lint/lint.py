#!/usr/bin/env python3
"""Presence lint for the standard notify-failure job.

Two rules, both syntactic:

A — A workflow is COVERED iff its triggers include `push` or `schedule`
    (regardless of what else they include). A covered workflow must carry
    the standard notify-failure job, or declare a semantic-notifier
    exemption.

C — No workflow may announce failure off a hand-maintained enumeration of
    workflows. Decided syntactically on `on.workflow_run.workflows`: a list
    of workflow DISPLAY names, matched exactly, with no wildcard support and
    no signal when an entry stops matching anything. That is the construct
    the original defect was built on.

There is no filename allowlist anywhere in this checker: the covered
decision comes from the workflow's own triggers and the exemption from a
marker inside the workflow file, so no hand-maintained list of workflow
names exists to drift.

Implements: HHT-OPS-failure-notification-routing/E
Verifies:   HHT-OPS-failure-notification-routing/A+C
"""
import re
import sys
import os
import yaml

NOTIFY_JOB = "notify-failure"
COVERED_TRIGGERS = ("push", "schedule")
MARKER = "# notify-failure: semantic-exempt"

CANONICAL_IF = (
    "${{ !cancelled() && contains(needs.*.result, 'failure') "
    "&& (github.event_name == 'push' || github.event_name == 'schedule') }}"
)

_WS = re.compile(r"\s+")


def _norm(text):
    """Collapse whitespace so YAML folding (>-, |) compares equal."""
    return _WS.sub(" ", str(text or "")).strip()


def _on_block(wf):
    # YAML 1.1 parses the bare key `on:` as boolean True.
    return wf.get("on", wf.get(True))


def _triggers(wf):
    on = _on_block(wf)
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return list(on)
    if isinstance(on, dict):
        return list(on.keys())
    return []


def _has_guarded_slack_post(jobs):
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            uses = str(step.get("uses", ""))
            guard = _norm(step.get("if", ""))
            if "slack-notify" in uses and ("failure()" in guard or "always()" in guard):
                return True
    return False


def _check_no_workflow_enumeration(filename, wf):
    """Assertion C, decided syntactically on `on.workflow_run.workflows`.

    Evaluated for EVERY workflow, before the covered-trigger decision: the
    defect this rule exists to catch lived in a workflow_run-only workflow,
    which rule A never looks at.

    Implements: HHT-OPS-failure-notification-routing/E
    """
    on = _on_block(wf)
    if not isinstance(on, dict):
        return []
    trigger = on.get("workflow_run")
    if isinstance(trigger, dict) and "workflows" in trigger:
        return [f"{filename}: `on.workflow_run.workflows` is a hand-maintained "
                f"enumeration of workflow display names. It is matched exactly, "
                f"supports no wildcard, and reports nothing when an entry stops "
                f"matching — announce failure from inside each workflow with the "
                f"standard notify-failure job instead"]
    return []


def check(filename, source):
    """Return a list of violation strings; empty means the workflow conforms."""
    try:
        wf = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        return [f"{filename}: could not parse YAML ({exc})"]
    if not isinstance(wf, dict):
        return [f"{filename}: not a workflow mapping"]

    violations = _check_no_workflow_enumeration(filename, wf)

    triggers = _triggers(wf)
    if not any(t in COVERED_TRIGGERS for t in triggers):
        return violations  # exempt from rule A: no push/schedule trigger

    jobs = wf.get("jobs") or {}
    if not isinstance(jobs, dict):
        return violations + [f"{filename}: `jobs:` is not a mapping"]

    # Semantic-notifier carve-out: the marker is the enforced signal, and a
    # guarded slack-notify post must corroborate it so the marker cannot be
    # pasted onto a workflow that in fact announces nothing.
    if MARKER in source:
        if _has_guarded_slack_post(jobs):
            return violations
        return violations + [
            f"{filename}: carries the '{MARKER}' marker but has no "
            f"slack-notify step guarded by failure()/always()"]

    notify = jobs.get(NOTIFY_JOB)
    if not isinstance(notify, dict):
        return violations + [f"{filename}: is covered (push/schedule) but has "
                             f"no notify-failure job"]

    expected_needs = sorted(k for k in jobs if k != NOTIFY_JOB)
    declared = notify.get("needs") or []
    if isinstance(declared, str):
        declared = [declared]
    missing = sorted(set(expected_needs) - set(declared))
    if missing:
        violations.append(
            f"{filename}: notify-failure `needs:` is missing {missing}")

    if _norm(notify.get("if")) != _norm(CANONICAL_IF):
        violations.append(
            f"{filename}: notify-failure `if:` is not the canonical guard")

    perms = notify.get("permissions") or {}
    if not isinstance(perms, dict) or perms.get("actions") != "read":
        violations.append(
            f"{filename}: notify-failure must set `permissions: actions: read`")
    if not isinstance(perms, dict) or perms.get("contents") != "read":
        violations.append(
            f"{filename}: notify-failure must set `permissions: contents: read`")

    steps = notify.get("steps") or []
    uses_list = [str(s.get("uses", "")) for s in steps if isinstance(s, dict)]
    if not any(u.startswith("actions/checkout@") for u in uses_list):
        violations.append(
            f"{filename}: notify-failure needs an actions/checkout step "
            f"(slack-notify reads the routing file from the workspace)")

    notify_refs = [u for u in uses_list if "/notify-failure@" in u]
    if not notify_refs:
        violations.append(
            f"{filename}: notify-failure job does not use the notify-failure action")
    for ref in notify_refs:
        pin = ref.split("@", 1)[1]
        if not re.fullmatch(r"[0-9a-f]{40}", pin):
            violations.append(
                f"{filename}: notify-failure action must be pinned to a "
                f"40-character commit SHA (found '{pin}')")

    return violations


def main():
    workflows_dir = os.environ.get("INPUT_WORKFLOWS_DIR", ".github/workflows")
    all_violations = []
    for entry in sorted(os.listdir(workflows_dir)):
        if not entry.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(workflows_dir, entry)
        with open(path, encoding="utf-8") as handle:
            all_violations.extend(check(path, handle.read()))

    if all_violations:
        for violation in all_violations:
            print(f"::error::{violation}")
        print(f"\n{len(all_violations)} notify-failure violation(s).")
        print("Every workflow triggered by push or schedule must carry the "
              "standard notify-failure job (HHT-OPS-failure-notification-routing/A), "
              "and no workflow may announce failure off a hand-maintained "
              "enumeration of workflows (HHT-OPS-failure-notification-routing/C).")
        return 1
    print("All covered workflows carry the standard notify-failure job, "
          "and no workflow enumerates other workflows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
