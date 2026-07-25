# notify-failure

The single way a workflow announces its own failure to Slack.

## Usage

    notify-failure:
      name: Notify failure
      needs: [build, test]   # every OTHER job in the workflow
      if: ${{ !cancelled() && contains(needs.*.result, 'failure') && github.event_name != 'pull_request' }}
      runs-on: ubuntu-latest
      permissions:
        contents: read
        actions: read
      steps:
        - uses: actions/checkout@v4
        - uses: Cure-HHT/hht_workflows/.github/actions/notify-failure@<sha>
          with:
            slack-token: ${{ secrets.SLACK_BOT_TOKEN }}

Copy the `if:` guard verbatim — `notify-failure-lint` checks for it exactly.
It is deliberately not `failure()`: that also fires on a cancelled run. The
event test fires on everything **except** `pull_request` — push, schedule,
AND `workflow_dispatch` — because a dispatch failure can self-report just as a
push failure can. Only `pull_request` is excluded, since the author is already
looking at the PR's status checks.

## What it does

Derives which job — and, where identifiable, which step — failed from the
**current run's own** GitHub Actions jobs API. There is no per-workflow
configuration and no list of workflow names anywhere, so nothing can drift
out of sync. It composes the message and delegates delivery to the canonical
`slack-notify` composite (SHA-pinned internally).

**Delivery routing.** How the announcement is delivered depends on what
triggered the run:

- **`push` / `schedule`** — a channel post via the `event` route (default
  `workflow-failure` → the ops channel), plus a DM to the committer on a push
  (a scheduled run has no committer).
- **`workflow_dispatch`** — DM-first. GitHub Actions never exposes the
  triggering actor's email, so the action runs a best-effort cascade to
  resolve `github.actor` to one: the actor's public profile email, then the
  author email of their most recent commit (rejecting `*.noreply.github.com`
  privacy addresses). If it resolves, the failure is sent as a **DM to the
  triggerer only** — no channel post. If it does not resolve, the action
  falls back to a **channel post** whose body names the actor
  (`*Triggered by:* @<actor>`) so a human can still tell who dispatched it.

Either way a soft-failed delivery still surfaces an `::error::` annotation on
the run (see below) — in dm-only mode "success" means the DM was actually
sent, since there is no channel to fall back on.

If the announcement itself cannot reach Slack the post step is soft-failed —
a Slack outage must not repaint an otherwise green run — but an `::error::`
annotation is emitted so the failed announcement is visible on the run
without depending on Slack being up.

The caller **must** run `actions/checkout` first (`slack-notify` reads the
routing file from the caller's workspace) and grant `actions: read` (the jobs
lookup 403s without it).

## Inputs

| Input | Description | Default | Required |
|-------|-------------|---------|----------|
| `slack-token` | Slack bot OAuth token (`xoxb-...`). | — | Yes |
| `event` | Routing key looked up in the caller's routing YAML. The default is a FLAT key (single channel), so a caller with no build flavor passes no `env`. | `workflow-failure` | No |
| `env` | Routing sub-key. Pass ONLY when `event` names an env-keyed route — `slack-notify` errors by design on a flat/env-keyed mismatch. | `''` | No |
| `hints` | JSON object mapping a failed step's `name` (exactly as the jobs API reports it, not the step `id`) to hint text. Unmatched or absent produces no hint line; malformed JSON is warned about and ignored, never fatal. | `''` | No |
| `routing-file` | Path to the routing YAML, relative to the caller's workspace. | `.github/slack-channels.yml` | No |

## Outputs

| Output | Description |
|--------|-------------|
| `post-status` | `ok` when the announcement reached at least one channel, `soft-failed` otherwise (an `::error::` annotation accompanies `soft-failed`). |

## Why this exists

Implements `HHT-OPS-failure-notification-routing/A`, `/B` and `/D`. It
replaces a central watcher workflow that listened for completions of a
hand-typed list of workflow display names — a list that matched exactly, had
no wildcard, and reported nothing when an entry stopped matching. The
enforcement half that keeps that pattern from re-accreting is
[`notify-failure-lint`](../notify-failure-lint/).
