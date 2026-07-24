"""Unit tests for lint.py — run with: python3 -m pytest -q

Verifies: HHT-OPS-failure-notification-routing/E
"""
import lint

CANONICAL_IF = (
    "${{ !cancelled() && contains(needs.*.result, 'failure') "
    "&& (github.event_name == 'push' || github.event_name == 'schedule') }}"
)

GOOD = """
name: Example
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
  notify-failure:
    needs: [build]
    if: >-
      %s
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: read
    steps:
      - uses: actions/checkout@abc123
      - uses: Cure-HHT/hht_workflows/.github/actions/notify-failure@1111111111111111111111111111111111111111
        with:
          slack-token: x
""" % CANONICAL_IF


def test_good_workflow_passes():
    assert lint.check("good.yml", GOOD) == []


def test_pr_only_workflow_is_exempt():
    src = "name: X\non:\n  pull_request:\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"
    assert lint.check("pr.yml", src) == []


def test_dispatch_only_workflow_is_exempt():
    src = "name: X\non:\n  workflow_dispatch:\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"
    assert lint.check("d.yml", src) == []


def test_workflow_call_only_is_exempt():
    src = "name: X\non:\n  workflow_call:\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"
    assert lint.check("wc.yml", src) == []


def test_push_plus_dispatch_is_still_covered():
    src = "name: X\non:\n  push:\n  workflow_dispatch:\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"
    assert any("no notify-failure job" in v for v in lint.check("x.yml", src))


def test_schedule_is_covered():
    src = "name: X\non:\n  schedule:\n    - cron: '0 9 1 * *'\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n"
    assert any("no notify-failure job" in v for v in lint.check("s.yml", src))


def test_needs_must_name_every_other_job():
    src = GOOD.replace("jobs:\n  build:", "jobs:\n  extra:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n  build:")
    assert any("needs" in v and "extra" in v for v in lint.check("x.yml", src))


def test_wrong_if_guard_is_rejected():
    src = GOOD.replace(CANONICAL_IF, "${{ failure() }}")
    assert any("canonical" in v for v in lint.check("x.yml", src))


def test_missing_actions_read_is_rejected():
    src = GOOD.replace("      actions: read\n", "")
    assert any("actions: read" in v for v in lint.check("x.yml", src))


def test_missing_checkout_is_rejected():
    src = GOOD.replace("      - uses: actions/checkout@abc123\n", "")
    assert any("checkout" in v for v in lint.check("x.yml", src))


def test_unpinned_composite_ref_is_rejected():
    src = GOOD.replace(
        "notify-failure@1111111111111111111111111111111111111111", "notify-failure@main")
    assert any("SHA" in v for v in lint.check("x.yml", src))


def test_semantic_exempt_marker_with_guarded_post_passes():
    src = """# notify-failure: semantic-exempt
name: Maint
on:
  schedule:
    - cron: '0 9 1 * *'
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: Notify
        if: failure()
        uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@abc
"""
    assert lint.check("m.yml", src) == []


def test_marker_without_a_guarded_post_is_rejected():
    src = """# notify-failure: semantic-exempt
name: Maint
on:
  schedule:
    - cron: '0 9 1 * *'
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: echo no post here
"""
    assert any("semantic-exempt" in v for v in lint.check("m.yml", src))


# --- Assertion C: no hand-maintained enumeration of workflows -------------
# The check is syntactic, per the requirement's Rationale: a workflow fails
# if its `on:` block carries a `workflow_run.workflows` list. That list is
# the construct that caused the original defect — display names typed by
# hand, matched exactly, with no wildcard and no failure signal when they
# stop matching anything.

WORKFLOW_RUN_ENUM = """
name: Pager
on:
  workflow_run:
    workflows: ["Build", "Test"]
    types: [completed]
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: echo
"""


def test_workflow_run_enumeration_is_rejected():
    violations = lint.check("pager.yml", WORKFLOW_RUN_ENUM)
    assert any("workflow_run" in v and "enumeration" in v for v in violations)


def test_workflow_run_without_workflows_key_is_not_an_enumeration():
    src = """
name: Pager
on:
  workflow_run:
    types: [completed]
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: echo
"""
    # It enumerates nothing, so rule C must stay silent. It is also not
    # push/schedule triggered, so rule A does not apply either.
    assert lint.check("pager.yml", src) == []


def test_enumeration_is_flagged_even_on_an_otherwise_conforming_workflow():
    # Rule C is independent of rule A: a workflow can carry the standard
    # notify-failure job and still smuggle in a workflow-name list.
    src = GOOD.replace(
        "on:\n  push:\n    branches: [main]\n",
        "on:\n  push:\n    branches: [main]\n  workflow_run:\n    workflows: [\"Build\"]\n",
    )
    violations = lint.check("x.yml", src)
    assert any("enumeration" in v for v in violations)
    assert not any("no notify-failure job" in v for v in violations)


def test_enumeration_is_flagged_on_an_otherwise_exempt_workflow():
    # The original defect's workflow was workflow_run-triggered only, so it
    # is not "covered" by rule A. Rule C must be evaluated before the
    # covered-trigger early return, or the defect stays undetectable.
    assert lint.check("pager.yml", WORKFLOW_RUN_ENUM) != []


def test_enumeration_is_flagged_under_a_semantic_exempt_marker():
    # The marker is a carve-out from rule A only. It must not buy silence
    # on rule C.
    src = """# notify-failure: semantic-exempt
name: Maint
on:
  schedule:
    - cron: '0 9 1 * *'
  workflow_run:
    workflows: ["Build"]
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: Notify
        if: failure()
        uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@abc
"""
    violations = lint.check("m.yml", src)
    assert any("enumeration" in v for v in violations)
    assert not any("semantic-exempt" in v for v in violations)


def test_bare_on_key_parsed_as_boolean_true_still_sees_the_enumeration():
    # YAML 1.1 parses the bare key `on:` as boolean True; the C check must
    # use the same accessor as the trigger read, not wf["on"].
    import yaml
    assert True in yaml.safe_load(WORKFLOW_RUN_ENUM)
    assert any("enumeration" in v for v in lint.check("p.yml", WORKFLOW_RUN_ENUM))
