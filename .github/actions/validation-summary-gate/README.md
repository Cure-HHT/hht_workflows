# validation-summary-gate

Publishes the org ruleset's required `Validation Summary` check without
holding a runner. It replaces the polling action
[`validation-summary`](../validation-summary/), which kept a runner asking
GitHub every 30 seconds whether the other checks had finished (28 minutes per
pull request on average in hht_diary, up to 190).

Why this exists: `HHT-OPS-composite-action-library/A` — the merge gate is a
cross-repo CI primitive, so its logic lives here once and five repositories
pin it.

## How it works

A workflow on the default branch is triggered by `workflow_run` (every
workflow finishing, plus the start of the workflows that re-run on PR
`edited`) and by `check_run: completed` (check runs from GitHub Apps other
than GitHub Actions). Each firing runs one short job that:

1. Ignores the event unless the triggering run was for a pull request and
   its head commit is the **current head of an open pull request into the
   gated base branch** (default `main`). Push-to-main runs, superseded
   commits and closed PRs are left alone.
2. Reads the commit's check runs and workflow runs **once**, and decides:

   | Seen on the head commit (newest check run of each name) | Verdict |
   | --- | --- |
   | any check run not completed, or any workflow run queued / in progress / waiting / awaiting approval | `pending` (published as an in-progress check run listing what it waits for) |
   | a `cancelled` check run | `pending` — waiting for a re-run (see below) |
   | everything completed, any `failure`, `timed_out`, `action_required`, `startup_failure` or `stale` | `failure` |
   | everything completed as `success`, `skipped` or `neutral` | `success` |
   | no check runs at all | `pending` |

   Check runs named like the gate (`Validation Summary` — the old polling
   job and the gate's own earlier check runs) are never counted, nor are runs
   of the gate's workflow or of the `dynamic` event (the Copilot review
   agent).
3. Publishes a check run named `Validation Summary` on the commit through the
   Checks API. An in-progress gate check run is updated in place; once
   completed it is never reopened — a changed state gets a new check run, so
   the newest check run of that name is always the current verdict.
4. On `failure`, upserts one PR comment (marker
   `<!-- pr-comment-upsert:validation-summary -->`) with the failed checks,
   their failure annotations or failed step names, and a link to the run. On
   `success`, removes that comment and the two earlier generations
   (`<!-- validation-summary -->`, `<!-- ci-gate-summary -->`).

The job succeeds whenever it published a verdict. A red gate *run* means
the gate itself broke; it then publishes a `failure` check run saying it
could not evaluate, so an earlier pass never stands as the newest verdict.

### The race between workflows that finish together

The concurrency group is per head commit, on the job, with
`cancel-in-progress: false`: a running evaluation is never cancelled, and a
newer queued evaluation replaces an older queued one. Because a
`completed` event is delivered only after its run has finished, and a
replacing evaluation starts later than the one it replaced, the evaluation
fired by the **last** workflow to finish always runs and finds every check
complete. What remains is API lag — the listing can trail the event by a few
seconds — so when the listing visibly contradicts the event (the triggering
run, or a check run of an already-completed suite, still reads as running),
the gate re-reads up to `relist-attempts` times, `relist-interval-seconds`
apart (3 × 20 s by default), before publishing.

### Cancelled checks

A cancelled check is treated as pending while anything else is pending or a
re-run of its workflow is queued. If nothing else is pending and no re-run
appears within the bounded re-read, the gate reports `failure` ("cancelled and
not re-run") instead of waiting forever; re-running the cancelled workflow
fires a new evaluation. The polling gate reached the same verdict after its
time budget ran out.

## Usage

The wrapper must live on the default branch; `workflow_run` and `check_run`
always run the default-branch copy. Copy it verbatim and set the list in
`if:` to the workflows of your repo that run on `pull_request: edited`.

```yaml
name: Validation Summary Gate

on:
  workflow_run:
    workflows: ["**", "!Validation Summary Gate"]
    types: [completed, requested]
  check_run:
    types: [completed]

permissions:
  checks: write
  pull-requests: write
  actions: read
  contents: read

jobs:
  evaluate:
    name: Evaluate Validation Summary
    if: >-
      (github.event_name == 'check_run'
        && github.event.check_run.app.slug != 'github-actions')
      || (github.event_name == 'workflow_run'
        && contains(fromJSON('["pull_request", "pull_request_target"]'), github.event.workflow_run.event)
        && github.event.workflow_run.name != 'Validation Summary'
        && (github.event.action == 'completed'
          || contains(fromJSON('["Validate PR Title"]'), github.event.workflow_run.name)))
    runs-on: ubuntu-latest
    timeout-minutes: 5
    concurrency:
      group: validation-summary-gate-${{ github.event.workflow_run.head_sha || github.event.check_run.head_sha }}
      cancel-in-progress: false
    steps:
      - uses: Cure-HHT/hht_workflows/.github/actions/validation-summary-gate@<commit-sha>  # SHA-pin
```

- `workflows: ["**", "!Validation Summary Gate"]` selects every workflow but
  the gate itself. GitHub's `workflows` filter takes glob patterns, so no
  workflow name has to be listed and a new workflow cannot escape the gate.
  `notify-failure-lint` accepts exactly this filter and rejects any other.
- Do not give the wrapper a `pull_request` trigger and do not check out the
  pull request: the job runs with base-repository permissions, fork PRs
  included.
- The job is deliberately **not** named `Validation Summary`: its own check
  run lands on the default branch's commit, and the required context is the
  check run the action creates on the PR head.

### Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `check-name` | `Validation Summary` | Name of the published check run; must equal the ruleset's required context |
| `base-branch` | `main` | Only PRs into this branch are gated |
| `ignore-workflows` | `Validation Summary`, `Validation Summary Gate` | Workflow names whose runs and check runs are not counted |
| `relist-attempts` | `3` | Re-reads while the listing lags the event |
| `relist-interval-seconds` | `20` | Seconds between re-reads |
| `github-token` | `github.token` | Needs `checks: write`, `pull-requests: write`, `actions: read`, `contents: read` |

Output `verdict`: `success`, `failure` or `pending` (empty when the event was
not for an open PR head).

## Moving a repository from the polling gate

The pull request that adds the wrapper cannot be gated by it — `workflow_run`
runs only from the default branch — so keep the polling workflow in that pull
request. After it merges, both publish `Validation Summary` on every PR
commit. Whichever of the two GitHub takes as the newest, no commit can pass
that the polling gate alone would have blocked: both read the same checks,
the polling gate's extra failures (its timeout, its cancellation by an
`edited` restart) only block, and every change after the polling gate's
verdict (a re-run) produces a newer gate check run. A second pull request then deletes the polling workflow; that pull
request is itself the first one gated only by this action.

## Tests

```sh
cd .github/actions/validation-summary-gate && PYTHONPATH=. pytest tests/ -v
```

`tests/fixtures/` holds check runs and workflow runs recorded read-only from
real pull requests in the public `hht_workflows` and `event_sourcing`
repositories; each test asserts the gate reaches the verdict the polling gate
recorded for that commit.
