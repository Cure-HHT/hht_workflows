# notify-failure-lint

The enforcement half of [`notify-failure`](../notify-failure/): a static
check that fails CI so bespoke per-workflow failure notifiers cannot silently
re-accrete.

## Usage

    notify-failure-lint:
      name: notify-failure lint
      runs-on: ubuntu-latest
      permissions:
        contents: read
      steps:
        - uses: actions/checkout@v4
        - uses: Cure-HHT/hht_workflows/.github/actions/notify-failure-lint@<sha>

The caller **must** run `actions/checkout` first — the lint reads the
workflow tree from the workspace.

`actions/setup-python` is optional. The action needs PyYAML, prefers whatever
the runner already provides, and installs it only when `import yaml` fails —
so it works on a bare runner and does not trip over a PEP 668
externally-managed interpreter.

## Rules

**A — Presence.** A workflow is *covered* if its triggers include `push`,
`schedule`, or `workflow_dispatch` (whatever else they include) — i.e.
anything not triggered *exclusively* by `pull_request` and/or
`workflow_call`. Every covered workflow must carry the standard
`notify-failure` job: `needs:` naming every other job, the canonical `if:`
guard verbatim, explicit `contents: read` + `actions: read`
(`permissions: read-all` is rejected — the grant must be legible in the
diff), an `actions/checkout` step, and a `notify-failure` reference pinned to
a 40-character commit SHA. Workflows triggered only by `pull_request`
(failures already show as PR status checks) and/or `workflow_call` (the
reusable workflow's caller announces) are out of scope.

The canonical `if:` guard is
`${{ !cancelled() && contains(needs.*.result, 'failure') && github.event_name != 'pull_request' }}`
— it fires on push, schedule, and `workflow_dispatch` failures, excluding
only `pull_request`.

**C — No workflow enumeration.** Two limbs. The `on:` block must not carry a
`workflow_run.workflows` list, *and* a job containing a `slack-notify` step
must not match `github.event.workflow_run.name` against a list read from a
file or an input. Such a list holds workflow *display names*, matched
exactly, with no wildcard and no signal when an entry stops matching — moving
it out of `on:` and into a text file changes none of that. Limb 2 reads
`run:` bodies and `if:` expressions (step- and job-level), so
`contains(fromJSON(vars.WATCHED_WORKFLOWS), github.event.workflow_run.name)`
on a `slack-notify` step is rejected too. This rule has no exemption and is
evaluated for every workflow, covered or not.

Limb 2 is a deliberately narrow proxy, so it under-fires by design rather
than blocking legitimate workflows. The name must be an argument of a real
*matching* command (`grep`/`rg`/`comm`/`look`, or `contains()` over an
`inputs.`/`vars.` value) — merely mentioning `workflow_run.name` in message
text, passing an unrelated `${{ inputs.channel }}`, or `cat`ing an unrelated
config file alongside it is fine. It also looks only within a single job: a
lookup performed in one job and announced from a `needs:`-dependent job is
not detected. Following `needs:` chains would be disproportionate here —
limb 1 plus review covers the construct that actually caused the defect.

There is no allowlist of workflow filenames in the checker: covered-ness
comes from each workflow's own triggers, so there is nothing to keep in sync.

## Semantic exemption

A workflow that announces failure with genuinely custom semantics can opt out
of rule A with a real comment line stating the outcome classification it
publishes:

    # notify-failure: semantic-exempt - posts a monthly maintenance summary, failures included

Three things are required, none sufficient alone: the marker must be an
actual top-level comment line, with `#` in **column 0** (the same text inside
a `run:` string — quoted or inside a `run: |` block scalar, where it is just
a shell comment — is not an exemption); it must state a classification after
a `-`, `:` or em-dash separator, carrying at least three consecutive letters
so `- .` does not pass; and the workflow must contain a
`slack-notify` step guarded by `failure()` or `always()`. Accepted exemptions
are printed on the check's own log as `file -> classification`, which is the
artifact a reviewer judges the carve-out by.

## Inputs

| Input | Description | Default | Required |
|-------|-------------|---------|----------|
| `workflows-dir` | Directory of workflow YAML to check, relative to the workspace. Naming a directory with no `.yml`/`.yaml` files is a failure, not a pass. | `.github/workflows` | No |

No outputs; the action fails the step, emitting one `::error::` annotation
per violation.

## Development

    cd .github/actions/notify-failure-lint
    python3 -m pytest -q

`fixtures/` holds one directory per outcome — `good/`, `bad/` (rule A),
`bad-enumeration/` (rule C limb 1), `bad-enumeration-lookup/` (rule C limb
2). One rule per directory is deliberate: a single `bad/` dir holding every
violating fixture would stay red on whichever rule still worked, so a
silently regressed rule would leave the readiness job green.

## Why this exists

Implements `HHT-OPS-failure-notification-routing/E` and verifies `/A` + `/C`.
