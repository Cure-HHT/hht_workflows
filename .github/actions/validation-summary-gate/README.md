# validation-summary-gate

Publishes the org ruleset's required `Validation Summary` context, as a
**commit status**, without holding a runner. It replaces the polling action
[`validation-summary`](../validation-summary/), which kept a runner asking
GitHub every 30 seconds whether the other checks had finished (28 minutes per
pull request on average in hht_diary, up to 190).

Why this exists: `HHT-OPS-composite-action-library/A` — the merge gate is a
cross-repo CI primitive, so its logic lives here once and five repositories
pin it.

## How it works

A workflow on the default branch is triggered by `workflow_run` (every
workflow starting or finishing, whatever event raised it) and by
`check_run` `created` and `completed` (check runs from GitHub Apps other
than GitHub Actions). Each firing runs one short job that:

1. Ignores the event unless its head commit is the **current head of an
   open pull request into the gated base branch** (default `main`).
   Push-to-main runs, superseded commits and closed PRs are left alone after
   one API call. A push, review, label, re-run or dispatch run on a pull
   request's head is evaluated like a `pull_request` run: the verdict counts
   it, so its start and its end must each move the verdict.
2. Posts `pending` on the commit, so a job that dies mid-evaluation never
   leaves an earlier pass standing.
3. Reads the commit's check runs (`filter=all`) and workflow runs **once**,
   and decides:

   | Seen on the head commit (newest check run of each job, per workflow) | Verdict |
   | --- | --- |
   | any check run not completed, or any workflow run queued / in progress / waiting / awaiting approval | `pending` (the status description lists what it waits for) |
   | a `cancelled` check run, or a cancelled workflow run with no check runs | `pending` — waiting for a re-run (see below) |
   | everything completed, any check run or workflow run `failure`, `timed_out`, `action_required`, `startup_failure`, `stale` or unknown (a workflow with a YAML error has a failed run and no check runs) | `failure` |
   | everything completed as `success`, `skipped` or `neutral` | `success` |
   | no check runs at all | `pending` |

   "Newest" is decided per workflow (through the check's suite), so two
   workflows that both have a job called `check` are two checks. Nothing is
   skipped by name, because a pull request controls every workflow, job and
   check name: the old polling job's `Validation Summary` check run is
   counted like any other check. Commit statuses are never read (so the
   gate's own status cannot feed back). Runs of the gate's own workflow are
   recognised by its file path together with a non-pull-request event, and
   are not counted, nor are runs of the `dynamic` event (the Copilot review
   agent). Any other workflow named like the gate's workflow is a
   **failure**, since it reads as the gate in every listing.

   The gate does not stop a same-repo pull request from adding a workflow
   with `statuses: write` that posts `Validation Summary` itself after every
   other check has finished. The polling job was open to the same attack.
   Closing it needs a dedicated GitHub App to post the status and the
   required check pinned to that App's `integration_id` (a follow-up); until
   then, review of `.github/workflows/` changes guards it.
4. Posts the commit status `Validation Summary` on the commit
   (`pending`, `success`, `failure`, or `error` when the gate itself could not
   evaluate), description at most 140 characters, linking to the gate's run.
   The newest status of a context is the one that counts.
5. On `failure`, upserts one PR comment (marker
   `<!-- pr-comment-upsert:validation-summary -->`) with the failed checks,
   their failure annotations or failed step names, and a link to the run. On
   `success`, removes that comment and the two earlier generations
   (`<!-- validation-summary -->`, `<!-- ci-gate-summary -->`). Only comments
   written by `github-actions[bot]` are touched: anyone can post a comment that
   starts with a marker. Names and annotation text taken from the pull
   request are neutralised first: no line break, no `::` workflow command,
   no `@` mention.

The job succeeds whenever it published a verdict. A red gate *run* means
the gate itself broke — a malformed input, a failure to list pull requests
or to publish; it then posts an `error` status saying it could not evaluate.
If the evaluation step crashes, times out or is cancelled before it can, the
wrapper's last step (`mode: job-failed`) posts `error` on the head commit.
Either way an earlier pass never stands as the newest verdict.

### Why a commit status and not a check run

GitHub counts checks created by workflow jobs toward a ruleset only when the
run was triggered by `push`, `pull_request`, `pull_request_review`,
`pull_request_target`, `deployment` or `deployment_status` (docs:
"Troubleshooting required status checks"); `workflow_run` is not one of them,
and nothing documents that a check run created through the Checks API with the
workflow's token escapes that. A required context is satisfied by a commit
status as well, and "if a check and a commit status have the same name, both
must pass when that name is required".

### When it can stay pending

Every pending verdict is followed by another evaluation when the next
workflow finishes, except in two cases: the bounded re-read ran out while the
listing still lagged, or what is still pending is another GitHub App's check
run. GitHub does not fire `check_run` "if the check run's check suite was
created by GitHub Actions or if the check suite's head SHA is associated with
GitHub Actions", and every PR commit has Actions suites. In both cases the
status description ends with "if stuck, re-run the Validation Summary Gate
workflow" and the summary explains it: re-run the latest **Validation Summary
Gate** run from the Actions tab, and it re-reads everything.

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
always run the default-branch copy. Copy it verbatim.

```yaml
name: Validation Summary Gate

on:
  workflow_run:
    workflows: ["**"]
    types: [completed, requested]
  check_run:
    types: [created, completed]

permissions: {}

jobs:
  evaluate:
    name: Evaluate Validation Summary
    if: >-
      (github.event_name == 'workflow_run'
        && !(github.event.workflow_run.path == '.github/workflows/validation-summary-gate.yml'
          && !contains(fromJSON('["pull_request", "pull_request_target"]'), github.event.workflow_run.event)))
      || (github.event_name == 'check_run'
        && github.event.check_run.app.slug != 'github-actions')
    runs-on: ubuntu-latest
    timeout-minutes: 5
    permissions:
      statuses: write
      checks: read
      pull-requests: write
      actions: read
      contents: read
    concurrency:
      group: validation-summary-gate-${{ github.event.workflow_run.head_sha || github.event.check_run.head_sha }}
      cancel-in-progress: false
    steps:
      - uses: Cure-HHT/hht_workflows/.github/actions/validation-summary-gate@<commit-sha>  # SHA-pin
      - if: failure() || cancelled()
        uses: Cure-HHT/hht_workflows/.github/actions/validation-summary-gate@<commit-sha>  # SHA-pin
        with:
          mode: job-failed
```

- Copy it verbatim; there is no per-repo list to maintain.
- `workflows: ["**"]` selects every workflow, so no workflow name has to be
  listed and a new workflow cannot escape the gate. The gate's own runs are
  skipped by the job's `if:`, on the run's file path and a non-pull-request
  event, never on a name: a name-based exclusion (`"!Validation Summary
  Gate"`) would let a pull request add a workflow wearing that name whose
  start and end never fire the gate, and which could post the status
  itself after the gate's last evaluation. A skipped run of the gate is
  itself a `workflow_run`, which the same `if:` skips; GitHub stops such a
  chain after three levels. `notify-failure-lint` accepts `["**"]`.
- `check_run: [created, completed]`: another app's check that starts after
  a pass sets the status back to pending at once, rather than leaving the
  pass standing until that check finishes.
- The wrapper must live at `.github/workflows/validation-summary-gate.yml`
  and keep `name: Validation Summary Gate`, or set `gate-workflow-path` /
  `gate-workflow-name` to match.
- Do not give the wrapper a `pull_request` trigger and do not check out the
  pull request: the job runs with base-repository permissions, fork PRs
  included.
- The job is deliberately **not** named `Validation Summary`: its own check
  run lands on the default branch's commit, and the required context is the
  commit status the action posts on the PR head.

### Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `check-name` | `Validation Summary` | Commit-status context to publish; must equal the ruleset's required context |
| `base-branch` | `main` | Only PRs into this branch are gated |
| `gate-workflow-path` | `.github/workflows/validation-summary-gate.yml` | The wrapper's file; its non-pull-request runs are not counted |
| `gate-workflow-name` | `Validation Summary Gate` | The wrapper's `name:`; any other workflow with this name fails the gate |
| `mode` | `evaluate` | `job-failed` posts `error` on the head commit (the wrapper's `if: failure() \|\| cancelled()` step) |
| `relist-attempts` | `3` | Re-reads while the listing lags the event |
| `relist-interval-seconds` | `20` | Seconds between re-reads |
| `github-token` | `github.token` | Needs `statuses: write`, `checks: read`, `pull-requests: write`, `actions: read`, `contents: read` |

Output `verdict`: `success`, `failure` or `pending` (empty when the event was
not for an open PR head).

## Moving a repository from the polling gate

The pull request that adds the wrapper cannot be gated by it — `workflow_run`
runs only from the default branch — so keep the polling workflow in that pull
request. After it merges, every PR commit carries the polling job's
`Validation Summary` **check run** and the gate's `Validation Summary`
**commit status**, and both must pass. The gate counts the polling job's
check run like any other check, so its status settles about 30 seconds
after the polling job finishes. That phase is a live test of the gate:
a gate that wrongly fails or never finishes blocks merges, it cannot let one
through that the polling gate would have blocked.

To back out in that phase, disable the gate workflow (Actions → Validation
Summary Gate → Disable workflow) and push: new commits carry only the polling
check run, which then satisfies the context alone. Merging past a stuck status
would need an override, and the rulesets have no bypass actors
(`HHT-OPS-cicd-app-operations/D`), so that means a ruleset change in hht_admin
Terraform — prefer disabling.

A second pull request then deletes the polling workflow; that pull request is
itself the first one gated only by this action.

## Tests

```sh
cd .github/actions/validation-summary-gate && PYTHONPATH=. pytest tests/ -v
```

`tests/fixtures/` holds check runs and workflow runs recorded read-only from
real pull requests in the public `hht_workflows` and `event_sourcing`
repositories; each test asserts the gate reaches the verdict the polling gate
recorded for that commit.
