# pr-comment-upsert

Find a PR comment by its hidden marker prefix and update it in place; create
a new one if no match exists; delete any duplicates. Replaces the
"append a fresh comment every run" anti-pattern that fills PR threads with
stale CI output.

## Usage

```yaml
permissions:
  contents: read
  pull-requests: write   # REQUIRED

steps:
  - name: 'Post / update plan comment'
    uses: Cure-HHT/hht_workflows/.github/actions/pr-comment-upsert@<sha>
    with:
      marker: '<!-- pr-comment-upsert:terraform-plan -->'
      body: |
        <!-- pr-comment-upsert:terraform-plan -->
        ### Terraform Plan

        <details><summary>Plan output</summary>

        ```
        ${{ steps.plan.outputs.stdout }}
        ```

        </details>

        Status: ${{ steps.plan.outputs.exitcode == '0' && 'succeeded' || 'failed' }}
```

The first line of `body` MUST be the `marker` exactly. The action enforces
this so a typo cannot silently degrade to "create a new comment every run".

## Marker convention

`<!-- pr-comment-upsert:<kebab-id> -->`

`<kebab-id>` should name the check posting the comment (e.g. `manifest-staleness`,
`terraform-plan`, `pr-health`, `secrets-drift`). Pick something stable; if you
change it later, the action loses track of prior comments and they become
orphans on existing PRs.

## What it does

1. Lists all PR comments via `gh api`.
2. Filters by body starting with the marker.
3. If 2+ match, deletes the extras (collapse duplicates).
4. If 1 match, PATCHes it with the new body.
5. If 0 matches, POSTs a fresh comment.

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `marker` | yes | -- | HTML comment of form `<!-- ... -->`. Identifies this check's comment. |
| `body` | yes | -- | Full body. MUST start with `marker`. Max 65536 chars. |
| `pr_number` | no | `${{ github.event.pull_request.number }}` | PR to comment on. |
| `github_token` | no | `${{ github.token }}` | Token with `pull-requests: write`. |

## Outputs

| Output | Description |
| --- | --- |
| `comment_id` | Numeric ID of the upserted comment. |
| `action` | `updated` if a PATCH was issued; `created` if a fresh comment was POSTed. |

## Required workflow permissions

```yaml
permissions:
  contents: read
  pull-requests: write
```

## Breaks if

- `body` does not literally start with `marker` -> action errors out.
- `marker` is not an HTML comment -> errors out (defends against markdown-heading
  markers, which are visible to humans and can drift as wording evolves).
- `pr_number` is empty AND the event is not `pull_request` -> errors out (caller
  must supply the PR number explicitly for `schedule`/`workflow_dispatch`/etc.).
- Body exceeds 65536 chars -> errors out (GitHub's hard limit).
- Token lacks `pull-requests: write` -> POST/PATCH returns 403.

## Why this exists

CI checks that post comments on every run accumulate noise: stale plan output
from old commits, drift reports against outdated state, "this is fixed" comments
left behind after fixes. The replace-in-place pattern keeps the PR's comment
thread showing the CURRENT state of each check. The run logs and previous
comment versions remain available in run history; they are not lost.

The pattern was established in `hht_diary/.github/workflows/pr-health.yml`
and is generalized here so every check in the org can opt in with one step.
