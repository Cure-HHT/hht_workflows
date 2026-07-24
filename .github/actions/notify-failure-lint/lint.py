#!/usr/bin/env python3
"""Presence lint for the standard notify-failure job.

Two rules, both syntactic:

A — A workflow is COVERED iff its triggers include `push` or `schedule`
    (regardless of what else they include). A covered workflow must carry
    the standard notify-failure job, or declare a semantic-notifier
    exemption.

C — No workflow may announce failure off a hand-maintained enumeration of
    workflows. The requirement's Rationale fixes the criterion in two limbs:
    a workflow fails if its `on:` block contains a `workflow_run.workflows`
    list, OR if an announcement step reads a workflow enumeration from a
    file or an input. The first limb is the construct the original defect
    was built on; the second closes the obvious workaround of moving the
    same list of names out of `on:` and into a text file or an input.

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

# The exemption marker must be a REAL comment line, not any occurrence of the
# string anywhere in the file: a raw substring scan matches inside a `run:`
# body, so `- run: 'echo "# notify-failure: semantic-exempt"'` would buy
# silence.
#
# The marker is required at COLUMN 0 — no leading whitespace. Allowing indent
# reopens the same fail-open in block-scalar form: a shell comment inside a
# `run: |` body is textually identical to an indented YAML comment, so
#
#     - run: |
#         # notify-failure: semantic-exempt - just a shell comment
#
# would buy silence too. A block-scalar body is always indented past its
# parent key, so column 0 is a complete discriminator, and it is the form the
# README documents.
#
# Assertion A requires the exemption to state "the outcome classification it
# publishes, in a form the Assertion-E check enumerates" — so a trailing
# description after a `-`, `:` or em-dash separator is REQUIRED, and it must
# carry some substance (at least three consecutive letters): `- .` enumerates
# as `-> .`, which no reviewer can act on. main() prints every accepted
# exemption so a reviewer has an artifact.
_MARKER_LINE = re.compile(
    r"^#[ \t]*notify-failure:[ \t]*semantic-exempt[ \t]*(.*?)[ \t]*$",
    re.M)
_CLASSIFICATION = re.compile(r"^[-:—][ \t]*(?=[^\n]*[A-Za-z]{3})(\S.*)$")

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


def exemption(source):
    """Return (marker_present, classification_or_None) for `source`.

    Only a real comment line counts. `classification` is the non-empty text
    after the separator; None means the marker states no classification,
    which Assertion A does not permit.
    """
    match = _MARKER_LINE.search(source)
    if not match:
        return False, None
    tail = _CLASSIFICATION.match(match.group(1).strip())
    return True, tail.group(1).strip() if tail else None


# Assertion C, limb 2. The requirement's Rationale: "...or if an announcement
# step reads a workflow enumeration from a file or input."
#
# Implemented as a deliberately NARROW proxy so it cannot fire on ordinary
# message text: only inside a job that already carries a Slack-announcement
# step, and only for a `run:` body or an `if:` expression that BOTH names the
# workflow-run identity AND matches it against a file or a workflow input.
#
# The reference must be an ARGUMENT OF A MATCHING COMMAND, and the verb list
# holds only true matching verbs. A bare `${{ inputs.X }}` anywhere in a
# `run:` body is not evidence of an enumeration, and neither is `cat`/`sed`/
# `jq` of a file: both fire on legitimate workflows — `echo "Run of ${{
# github.event.workflow_run.name }} to ${{ inputs.channel }}"` and a `cat` of
# a channel-routing file — with a message that is untrue for them. So:
# `echo "Workflow ${{ github.event.workflow_run.name }} failed"` is untouched;
# `grep -qx "${{ github.event.workflow_run.name }}" .github/watched.txt` and
# `grep -q "${{ github.event.workflow_run.name }}" <<<"${{ vars.WATCHED }}"`
# are not.
_WORKFLOW_IDENTITY = re.compile(r"workflow_run\.(?:name|workflows)\b")
_ENUMERATION_LOOKUP = re.compile(
    # a matching command reading a data file or an input/vars-supplied list
    r"\b(?:grep|egrep|fgrep|rg|comm|look)\b[^\n]*"
    r"(?:\S+\.(?:txt|list|lst|json|ya?ml|csv)\b"
    r"|\$\{\{[ \t]*(?:inputs|vars)\.)")
# The same enumeration expressed as a GitHub expression in an `if:` rather
# than as shell. `contains(fromJSON(vars.WATCHED_WORKFLOWS), <identity>)` is
# the identical hand-maintained list, gating the identical announcement; the
# `run:`-only scan would have accepted it. The inputs/vars value must be the
# haystack argument of `contains()`, so an unrelated `inputs.enabled` in the
# same guard does not fire.
_ENUMERATION_IF = re.compile(
    r"contains\([ \t]*(?:fromJSON\([ \t]*)?(?:inputs|vars)\.[A-Za-z0-9_-]+")


def _check_no_enumeration_lookup(filename, jobs):
    """Assertion C limb 2. See the proxy note above.

    Implements: HHT-OPS-failure-notification-routing/E
    """
    violations = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
        if not any("slack-notify" in str(s.get("uses", "")) for s in steps):
            continue
        # (text, pattern) pairs: shell bodies and GitHub `if:` expressions
        # are different languages, so each gets its own lookup pattern.
        candidates = [(str(job.get("if", "")), _ENUMERATION_IF)]
        for step in steps:
            candidates.append((str(step.get("run", "")), _ENUMERATION_LOOKUP))
            candidates.append((str(step.get("if", "")), _ENUMERATION_IF))
        for body, pattern in candidates:
            if not body:
                continue
            if _WORKFLOW_IDENTITY.search(body) and pattern.search(body):
                violations.append(
                    f"{filename}: job '{job_id}' announces failure to Slack and "
                    f"matches the triggering workflow against an enumeration read "
                    f"from a file or input. Moving the workflow-name list out of "
                    f"`on.workflow_run.workflows` does not fix it — the list is "
                    f"still hand-maintained, still matched exactly, and still "
                    f"silent when an entry stops matching. Announce failure from "
                    f"inside each workflow with the standard notify-failure job")
                break
    return violations


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

    jobs = wf.get("jobs") or {}
    if isinstance(jobs, dict):
        violations += _check_no_enumeration_lookup(filename, jobs)

    triggers = _triggers(wf)
    if not any(t in COVERED_TRIGGERS for t in triggers):
        return violations  # exempt from rule A: no push/schedule trigger

    if not isinstance(jobs, dict):
        return violations + [f"{filename}: `jobs:` is not a mapping"]

    # Semantic-notifier carve-out. Three things are required, none of them
    # sufficient alone: the marker must be a real comment line (not a string
    # inside a `run:`), it must state the outcome classification the workflow
    # publishes (Assertion A), and a guarded slack-notify post must
    # corroborate it so the marker cannot be pasted onto a workflow that in
    # fact announces nothing.
    marked, classification = exemption(source)
    if marked:
        if classification is None:
            return violations + [
                f"{filename}: carries the '{MARKER}' marker but states no "
                f"outcome classification. Write "
                f"'{MARKER} - <what this workflow publishes on failure>' so "
                f"the exemption can be reviewed"]
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
    exemptions = []
    scanned = 0
    for entry in sorted(os.listdir(workflows_dir)):
        if not entry.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(workflows_dir, entry)
        scanned += 1
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        all_violations.extend(check(path, source))
        marked, classification = exemption(source)
        if marked and classification:
            exemptions.append((path, classification))

    # A `workflows-dir` typo that happens to name an existing directory would
    # otherwise report success while checking nothing at all.
    if scanned == 0:
        print(f"::error::{workflows_dir}: no .yml/.yaml workflow files found. "
              "Check the `workflows-dir` input and that actions/checkout ran "
              "before this step.")
        return 1

    if all_violations:
        for violation in all_violations:
            print(f"::error::{violation}")
        print(f"\n{len(all_violations)} notify-failure violation(s).")
        print("Every workflow triggered by push or schedule must carry the "
              "standard notify-failure job (HHT-OPS-failure-notification-routing/A), "
              "and no workflow may announce failure off a hand-maintained "
              "enumeration of workflows (HHT-OPS-failure-notification-routing/C).")
        return 1
    print(f"Scanned {scanned} workflow file(s). All covered workflows carry the "
          "standard notify-failure job, and no workflow enumerates other "
          "workflows.")
    # Assertion A: the exemption must state the outcome classification it
    # publishes "in a form the Assertion-E check enumerates" — this listing
    # is that form, so every exemption is visible on the check's own log.
    if exemptions:
        print(f"\nSemantic-notifier exemptions ({len(exemptions)}):")
        for path, classification in exemptions:
            print(f"  {path} -> {classification}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
