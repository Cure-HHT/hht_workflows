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
   - `bookmarks:read` + `bookmarks:write` (only when `bookmark-title` is
     set — see [Channel bookmark](#channel-bookmark))
   - `users:read.email` + `im:write` (only when `dm-user-email` is set —
     see [DM copy](#dm-copy))

## Inputs

| Name           | Required | Default                          | Purpose                                                                                                                       |
|----------------|----------|----------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| `event`        | channel mode | `""`                         | Top-level routing key in `routing.<event>`. Required in channel mode (empty is a hard `::error::`); in dm-only mode it is ignored and may be omitted.        |
| `env`          | no       | `""`                             | Sub-key for per-environment routing (`routing.<event>.<env>`).                                                                |
| `text`         | yes      | —                                | Slack mrkdwn body. When `blocks` is also supplied, this becomes the notification fallback / accessibility text.               |
| `blocks`       | no       | `""`                             | Optional Slack Block Kit `blocks` JSON string. When present, controls in-channel rendering; `text` is kept as the fallback.   |
| `bookmark-title` | no     | `""`                             | When non-empty, maintain a channel bookmark with this exact title pointing at the just-posted message. The title is the dedup key: an existing bookmark with the same title is edited; otherwise a new one is added. Opt-in (no auto-on). See [Channel bookmark](#channel-bookmark). |
| `slack-token`  | yes      | —                                | Bot OAuth token (`xoxb-...`).                                                                                                 |
| `routing-file` | no       | `.github/slack-channels.yml`     | Path relative to caller's workspace.                                                                                          |
| `dm-user-email` | no      | `""`                             | Optional email of a Slack workspace user who also receives the message as a DM after the channel posts. Failures are soft (warning only). See [DM copy](#dm-copy). |
| `dm-only`      | no       | `"false"`                        | When `"true"`, skip channel resolution/posting entirely and send ONLY the DM. `dm-user-email` becomes required (empty is a hard error); `event`/`env` are ignored. See [DM-only mode](#dm-only-mode). |
| `thread-reply-text` | no       | `""`                             | Optional mrkdwn body posted as a thread reply to the main message in each routed channel. Failures are soft (warning only). |

## Outputs

| Name           | Description                                                                                                                          |
|----------------|--------------------------------------------------------------------------------------------------------------------------------------|
| `channel-ids`  | Comma-separated list of channel IDs the message was posted to.                                                                       |
| `message-tss`  | Comma-separated chat.postMessage `ts` values, in the same order as `channel-ids`.                                                    |
| `bookmark-status` | Comma-separated per-channel bookmark outcome, aligned with `channel-ids`: `bookmarked` (added or edited), `skipped` (no `bookmark-title`), or `soft-failed` (Slack API error; deploy stayed green). |
| `dm-status`    | Outcome of the optional `dm-user-email` copy: `sent` (user resolved and DMed), `skipped` (no `dm-user-email`), or `soft-failed` (lookup or DM failed; warning emitted, action stayed green). |

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
  uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<commit-sha>  # SHA-pin to a release; see top-level README "Pinning & versioning"
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

## Channel bookmark

When `bookmark-title` is non-empty, the action maintains a single
channel bookmark with that exact title pointing at the just-posted
message's permalink. Bookmarks render as full-row entries under the
channel's Bookmarks tab (alongside Messages / Files), so descriptive
titles read well — e.g. `Cloud Run live versions (callisto / DEV)`
rather than a terse slot key.

This replaces the older "pin the deploy message" approach (which
Slack's `pinned_item` rendering made visually noisy for Block Kit
messages).

**How dedup works.** The bookmark `title` is the dedup key:

- If a bookmark with the given title already exists in the channel,
  the action calls `bookmarks.edit` to update its link to the new
  message permalink.
- Otherwise it calls `bookmarks.add` with the title + permalink.

Titles must therefore be **stable across runs for the same slot** —
typically embed `(<repo> / <env>)` or similar so each `(repo, env)`
pair has its own bookmark.

**Concurrent-run safety.** Two concurrent runs with the same title
will both `bookmarks.edit` the same entry; last writer wins. Since
`chat.postMessage` is serialized through Slack, the "last writer" is
the deploy whose post Slack accepted last.

**Failures are soft.** `chat.getPermalink`, `bookmarks.list`,
`bookmarks.add`, and `bookmarks.edit` errors emit `::warning::`
annotations and let the step stay green — the deploy already
succeeded; a Slack-side hiccup shouldn't paint it red. Any such
failure flips that channel's `bookmark-status` to `soft-failed`, so
callers can detect an incomplete cycle.

**Required scopes.** `bookmarks:read` + `bookmarks:write` on the bot
token (only when `bookmark-title` is set).

**Example.**

```yaml
- uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>
  with:
    event: deploy-success
    env:   ${{ inputs.sponsor-env }}
    text:  "..."
    bookmark-title: "Cloud Run live versions (callisto / ${{ inputs.sponsor-env }})"
    slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

**Disabling.** Omit `bookmark-title` (or set it to `""`) to skip the
bookmark cycle entirely. There is no auto-on / "always run for
`deploy-success*`" mode — bookmarks are opt-in, since not every caller
wants persistent channel-level state.

## DM copy

When `dm-user-email` is non-empty, the action — after the normal channel
routing/posting — resolves the Slack user via `users.lookupByEmail` and
sends the same `text`/`blocks` as a direct message (`chat.postMessage`
to the user ID). Use this when a specific person should be paged in
addition to the routed channels (e.g. the on-call owner of a pager
workflow).

**Failures are soft.** A lookup failure (no workspace user with that
email, missing `users:read.email` scope) or a DM post failure (missing
`im:write` scope) emits a `::warning::` and sets `dm-status` to
`soft-failed` — the action stays green, because the routed channels
already received the message. `dm-status` is `sent` on success and
`skipped` when the input is empty.

**Required scopes.** `users:read.email` (lookup) + `im:write` (open the
DM conversation) on the bot token — only when `dm-user-email` is set.

**Example.**

```yaml
- uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>
  with:
    event: deploy-failure
    env:   prod
    text:  ":rotating_light: prod deploy failed — <...|run>"
    dm-user-email: oncall@example.org
    slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

## DM-only mode

When `dm-only` is `"true"`, the action skips channel resolution and channel
posting completely — no `conversations.list`, no channel `chat.postMessage`,
no bookmark cycle — and sends **only** the DM to `dm-user-email`. Use this
when the message is meant for one person and there is no channel to route it
to (e.g. announcing a `workflow_dispatch` failure to the person who triggered
the run).

- `dm-user-email` is **required** in this mode. An empty value is a hard
  error (`::error::`, non-zero exit): dm-only with nobody to DM would notify
  no one, which is a misconfiguration rather than a soft Slack hiccup.
- `event` and `env` are **ignored** and may be omitted — no routing lookup
  happens. (In channel mode `event` is required: omitting it there is a hard
  `::error::`.)
- `channel-ids`, `message-tss`, and `bookmark-status` are emitted empty.
- The DM's soft-fail semantics are unchanged (a lookup/DM failure emits a
  `::warning::` and sets `dm-status: soft-failed`, and the action stays
  green), but because no channel received the message the warning says so
  explicitly — the caller is responsible for turning a dm-only soft-fail into
  a hard signal (as `notify-failure`'s status step does).

**Example.**

```yaml
- uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>
  with:
    dm-only: "true"
    dm-user-email: dispatcher@example.org
    text:  ":x: Your dispatched run failed — <...|run>"
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

Consumers **SHA-pin** this action like every other action in the repo
(`@<40-char-sha>`, never `@main` or a moving tag). Releases are
**repo-wide** semantic-version tags (`vX.Y.Z` + a moving `vMAJOR`); the
tag is a version label that lets a pinned SHA be mapped to a release
(Dependabot, the drift check). See the top-level `README.md` →
"Pinning & versioning" for the full policy.
