# `slack-notify` composite action

Resolves a routing key in the **caller's** `slack-channels.yml`, looks up
each target channel's ID via the Slack API, self-joins public channels,
and posts a `chat.postMessage` to each.

## Why this exists

Replaces the `secrets.SLACK_CHANNEL_DEVOPS`-by-channel-ID pattern across
Cure-HHT CI workflows with name-based routing. One bot token
(`SLACK_APP_OATH_TOKEN`) and one routing file per repo replaces N
hardcoded channel-ID secrets, and channel re-points stop requiring a
secret rotation.

## Caller prerequisites

1. The caller workflow has run `actions/checkout` (so the routing file
   is on disk).
2. The caller repo contains `.github/slack-channels.yml` (or whatever
   path is passed as `routing-file`) describing role keys → channel
   names + event/env → role keys.
3. The Slack bot token has these scopes:
   - `chat:write`
   - `channels:read` (for `conversations.list`)
   - `channels:join` (for public-channel self-heal)
   - `groups:read` (only if any routed channel is private)
   - `pins:write` (only when message pinning is enabled — see
     [Slack message pinning](#slack-message-pinning))

## Inputs

| Name           | Required | Default                          | Purpose                                                                                                                       |
|----------------|----------|----------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| `event`        | yes      | —                                | Top-level routing key in `routing.<event>`.                                                                                   |
| `env`          | no       | `""`                             | Sub-key for per-environment routing (`routing.<event>.<env>`).                                                                |
| `text`         | yes      | —                                | Slack mrkdwn body. When `blocks` is also supplied, this becomes the notification fallback / accessibility text.               |
| `blocks`       | no       | `""`                             | Optional Slack Block Kit `blocks` JSON string. When present, controls in-channel rendering; `text` is kept as the fallback.   |
| `pin`          | no       | `""`                             | Pin the posted message and unpin the prior pin for the same `(repo, env)`. Empty = auto-on for `deploy-success*` events; `"true"`/`"false"` overrides. See [Slack message pinning](#slack-message-pinning). |
| `slack-token`  | yes      | —                                | Bot OAuth token (`xoxb-...`).                                                                                                 |
| `routing-file` | no       | `.github/slack-channels.yml`     | Path relative to caller's workspace.                                                                                          |
| `thread-reply-text` | no       | `""`                             | Optional mrkdwn body posted as a thread reply to the main message in each routed channel. Failures are soft (warning only). |

## Outputs

| Name           | Description                                                                                                                          |
|----------------|--------------------------------------------------------------------------------------------------------------------------------------|
| `channel-ids`  | Comma-separated list of channel IDs the message was posted to.                                                                       |
| `message-tss`  | Comma-separated chat.postMessage `ts` values, in the same order as `channel-ids`.                                                    |
| `pin-status`   | Comma-separated per-channel pin outcome: `pinned`, `skipped` (pin disabled), or `soft-failed` (Slack API error; deploy stayed green). |

## Routing file shape

The action expects two top-level maps: `channels` (role key → channel
name) and `routing` (event[/env] → role key or list of role keys).

```yaml
channels:
  SLACK_DEV_DEPLOY_CH: "#dev"
  SLACK_QA_DEPLOY_CH:  "#qa"
  SLACK_DEVOPS_CH:     "#dev-ops"
  SLACK_BROADCAST_CH:  "#dev-ops"

routing:
  # env-keyed, single-channel
  deploy-success:
    dev:  SLACK_DEV_DEPLOY_CH
    qa:   SLACK_QA_DEPLOY_CH
    uat:  SLACK_BROADCAST_CH
    prod: SLACK_BROADCAST_CH

  # env-keyed, mixed single/list (qa-failure fans out)
  deploy-failure:
    dev:  SLACK_DEV_DEPLOY_CH
    qa:   [SLACK_QA_DEPLOY_CH, SLACK_DEVOPS_CH]
    uat:  SLACK_BROADCAST_CH
    prod: SLACK_BROADCAST_CH

  # flat (no env axis)
  android-build-success: SLACK_DEVOPS_CH
  ios-build-success:     SLACK_DEVOPS_CH
  maintenance-overdue:   SLACK_DEVOPS_CH
```

The leaf may be a single role key (string) or a list (fan-out). When
`env` is supplied, the action looks up `routing.<event>.<env>`; when
omitted, `routing.<event>` (must be a leaf, not a dict).

## Usage

```yaml
- uses: actions/checkout@v4

- name: Notify Slack on deploy success
  if: success()
  uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>  # slack-notify-vX.Y.Z
  with:
    event: deploy-success
    env: ${{ inputs.sponsor-env }}
    text: |
      :white_check_mark: *Cloud Run deploy succeeded*: `${{ inputs.service-name }}` -> `${{ inputs.sponsor-env }}`
      <${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}|View workflow run>
    slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

For an event with no env axis (e.g. android-build-success), simply omit
`env`:

```yaml
- uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>
  with:
    event: android-build-success
    text: ":robot_face: Android build deployed: ..."
    slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

For richer rendering — Block Kit table, dividers, rich_text, etc. —
pass `blocks` as a JSON string. `text` is still required and is sent
as the notification fallback / accessibility string. The action
validates that `blocks` parses as a JSON array before posting:

```yaml
- uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>
  with:
    event: deploy-success
    env: ${{ inputs.sponsor-env }}
    text: "Cloud Run Deploy Succeeded — see Slack for details"
    blocks: |
      [
        {"type":"section","text":{"type":"mrkdwn","text":"*Cloud Run Deploy Succeeded*"}},
        {"type":"table","rows":[
          [{"type":"raw_text","text":"env"},     {"type":"raw_text","text":"qa"}],
          [{"type":"raw_text","text":"version"}, {"type":"raw_text","text":"1.0.26"}]
        ]}
      ]
    slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

## Slack message pinning

When pinning is on, the posted message is pinned in each routed
channel and the bot's prior pinned message for the same `(repo, env)`
is unpinned. The intent is that a per-env Slack channel always has
one pinned message showing the current deployed version for that env,
regardless of how the deploy was triggered.

**When it runs.** Auto-on for any `event` matching `deploy-success` or
`deploy-success-*`. Force on/off with `pin: "true"` / `pin: "false"`.

**How the prior pin is identified.** Each pinned post carries Slack
message metadata:

```yaml
event_type: deploy_success_<repo_slug>_<env>
event_payload:
  repo:    <github.repository>          # e.g. Cure-HHT/hht_diary_callisto
  env:     <input env>                  # e.g. qa
  actor:   <github.actor>
  run_id:  <github.run_id>
  run_url: <github.server_url>/<github.repository>/actions/runs/<run_id>
  ts_iso:  <ISO-8601 UTC post time>
```

`repo_slug` is the basename of `github.repository`, lowercased, with
runs of non-alphanumerics collapsed to a single `_` and leading/trailing
underscores trimmed. So two repos posting to the same channel keep
separate pin slots, and (within a repo) each env keeps its own slot.

**Order is pin-then-unpin.** A failure adding the new pin leaves the
prior pin in place rather than emptying the channel's pin slot.

**Race-safe unpin.** Only pins with a strictly older `ts` than the
just-posted message are unpinned. Two concurrent deploy-success runs
will not race each other's pins out of existence — whichever wins the
ts ordering keeps its pin, and the other one's pin gets cleaned up by
the next deploy.

**Failures are soft.** `pins.add`, `pins.list`, and `pins.remove`
errors emit `::warning::` annotations and let the step stay green —
the deploy already succeeded; a Slack-side hiccup shouldn't paint it
red. Any failure beyond the initial `pins.add` (or `pins.add` itself)
flips that channel's `pin-status` to `soft-failed`, so callers can
detect an incomplete pin cycle.

**Required scope.** `pins:write` on the bot token (only when pinning
is on).

**Disabling on a per-call basis.** Set `pin: "false"`:

```yaml
- uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>
  with:
    event: deploy-success
    env:   ${{ inputs.sponsor-env }}
    pin:   "false"            # opt out of pin/unpin for this call
    text:  "..."
    slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

## Thread-reply pattern

Slack doesn't support markdown `<details>` collapsibles in messages, so for
long-form supplementary content the cleanest pattern is to post a concise
summary in-channel and the full content as a thread reply:

```yaml
- uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>
  with:
    event: deploy-success
    env:   prod
    text: |
      :rocket: Released `v1.2.3+5` — see thread for change list.
    thread-reply-text: |
      *Changes in v1.2.3+5*
      ${{ steps.notes.outputs.entries_block }}
    slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

When `thread-reply-text` is non-empty, the action makes one additional
`chat.postMessage` call per routed channel with `thread_ts` set to the main
post's `ts`. The call is best-effort; a failure emits a warning annotation
but does not fail the step (the main message already posted; a Slack-side
hiccup shouldn't paint a successful deploy red).

## Action version pinning

Two equally valid approaches in this repo (matching the convention for
the other actions here, see top-level `README.md`):

- **`@main`** — auto-update; a fix in this repo lands in all consumers
  on their next workflow run.
- **`@<commit-sha>` or `@<tag>`** — stable against unintended changes
  here.

Tag releases as `slack-notify-vX.Y.Z` (subdir-prefixed) since this repo
hosts multiple shared actions and a single repo-wide `v1` would
conflate them.
