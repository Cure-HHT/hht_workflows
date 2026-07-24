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

**A — Presence.** A workflow is *covered* if its triggers include `push` or
`schedule` (whatever else they include). Every covered workflow must carry
the standard `notify-failure` job: `needs:` naming every other job, the
canonical `if:` guard verbatim, explicit `contents: read` + `actions: read`
(`permissions: read-all` is rejected — the grant must be legible in the
diff), an `actions/checkout` step, and a `notify-failure` reference pinned to
a 40-character commit SHA. Workflows triggered only by `pull_request` /
`workflow_dispatch` / `workflow_call` are out of scope.

**C — No workflow enumeration.** Two limbs. The `on:` block must not carry a
`workflow_run.workflows` list, *and* a job containing a `slack-notify` step
must not match `github.event.workflow_run.name` against a list read from a
file or an input. Such a list holds workflow *display names*, matched
exactly, with no wildcard and no signal when an entry stops matching — moving
it out of `on:` and into a text file changes none of that. Merely mentioning
`workflow_run.name` in message text is fine. This rule has no exemption and
is evaluated for every workflow, covered or not.

There is no allowlist of workflow filenames in the checker: covered-ness
comes from each workflow's own triggers, so there is nothing to keep in sync.

## Semantic exemption

A workflow that announces failure with genuinely custom semantics can opt out
of rule A with a real comment line stating the outcome classification it
publishes:

    # notify-failure: semantic-exempt - posts a monthly maintenance summary, failures included

Three things are required, none sufficient alone: the marker must be an
actual comment line (`#` as the first non-blank character — the same text
inside a `run:` string is not an exemption); it must state a classification
after a `-`, `:` or em-dash separator; and the workflow must contain a
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
