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

## Inputs

| Name           | Required | Default                          | Purpose                                                                                |
|----------------|----------|----------------------------------|----------------------------------------------------------------------------------------|
| `event`        | yes      | —                                | Top-level routing key in `routing.<event>`.                                            |
| `env`          | no       | `""`                             | Sub-key for per-environment routing (`routing.<event>.<env>`).                         |
| `text`         | yes      | —                                | Slack mrkdwn body. Caller composes `@here`/`@channel` mentions and any URLs.           |
| `slack-token`  | yes      | —                                | Bot OAuth token (`xoxb-...`).                                                          |
| `routing-file` | no       | `.github/slack-channels.yml`     | Path relative to caller's workspace.                                                   |

## Outputs

| Name          | Description                                                    |
|---------------|----------------------------------------------------------------|
| `channel-ids` | Comma-separated list of channel IDs the message was posted to. |

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

## Pinning

Two equally valid approaches in this repo (matching the convention for
the other actions here, see top-level `README.md`):

- **`@main`** — auto-update; a fix in this repo lands in all consumers
  on their next workflow run.
- **`@<commit-sha>` or `@<tag>`** — stable against unintended changes
  here.

Tag releases as `slack-notify-vX.Y.Z` (subdir-prefixed) since this repo
hosts multiple shared actions and a single repo-wide `v1` would
conflate them.
