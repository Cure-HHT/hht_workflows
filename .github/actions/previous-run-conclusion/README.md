# `previous-run-conclusion` composite action

Determines the conclusion of the **previous completed run** of the
current workflow on the current branch. Built for pager workflows that
want to post a green "recovered" message after a red run — without a
state store, with one API call, using the ambient token (Linear ticket
CUR-1700).

## How it works

One `gh api` call to
`/repos/{owner}/{repo}/actions/workflows/{workflow}/runs?branch=<branch>&status=completed&per_page=5`,
then pick the most recent completed run whose id is not the current
`GITHUB_RUN_ID` and expose its `conclusion`.

## Inputs

| Name           | Required | Default                          | Purpose                                                                                     |
|----------------|----------|----------------------------------|---------------------------------------------------------------------------------------------|
| `github-token` | yes      | —                                | Token for the runs-list call. The ambient `${{ github.token }}` (`actions: read`) suffices. |
| `workflow`     | no       | current workflow file name       | Workflow file to query (e.g. `pager.yml`). Derived from `GITHUB_WORKFLOW_REF` when omitted. |
| `branch`       | no       | current branch                   | Branch to query (`GITHUB_HEAD_REF` on pull_request events, else `GITHUB_REF_NAME`).         |

## Outputs

| Name         | Description                                                                                                                                                                           |
|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `conclusion` | Previous completed run's conclusion: `success`, `failure`, `cancelled` (or any other GitHub conclusion string); `none` when no previous completed run exists; `unknown` on API failure (a `::warning::` is emitted, the action stays green). |

Callers should treat `none` and `unknown` conservatively — typically
"don't post a recovered message".

## Usage

```yaml
permissions:
  actions: read
  contents: read

steps:
  - name: What did the previous run conclude?
    id: prev
    uses: Cure-HHT/hht_workflows/.github/actions/previous-run-conclusion@<commit-sha>  # SHA-pin; see top-level README "Pinning & versioning"
    with:
      github-token: ${{ github.token }}

  - name: Post recovered message
    if: steps.prev.outputs.conclusion == 'failure'
    uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<commit-sha>
    with:
      event: pager-recovered
      text: ":white_check_mark: *Recovered* — previous run failed, this one is green."
      slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

## Notes

- The action always queries the **current repository**
  (`GITHUB_REPOSITORY`); cross-repo queries are not supported.
- An API failure is **soft** (`conclusion: unknown` + `::warning::`) —
  a flaky lookup must not fail the pager workflow that consumes it.
- Re-runs: the current run is excluded by id, so a re-run of the same
  run sees the run before it, not itself.

## Action version pinning

Consumers **SHA-pin** this action like every other action in the repo
(`@<40-char-sha>`, never `@main` or a moving tag). See the top-level
`README.md` → "Pinning & versioning" for the full policy.
