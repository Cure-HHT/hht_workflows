# release-notes-publish

Slices the top (current) version's section from `RELEASE_NOTES.md`, appends any
pending matching-version fragments from `.release-notes/`, and emits the result
as step outputs.

## Usage

```yaml
permissions:
  contents: read

steps:
  - uses: actions/checkout@v4
  - id: notes
    uses: Cure-HHT/hht_workflows/.github/actions/release-notes-publish@<sha>
  - name: Post to Slack
    uses: Cure-HHT/hht_workflows/.github/actions/slack-notify@<sha>
    with:
      event: deploy-success
      env: ${{ inputs.deploy-env }}
      text: |
        :rocket: *Released* `${{ steps.notes.outputs.version }}` to `${{ inputs.deploy-env }}`
      thread-reply-text: |
        ${{ steps.notes.outputs.entries_block }}
      slack-token: ${{ secrets.SLACK_APP_OATH_TOKEN }}
```

## Outputs

| Name           | Description |
| --- | --- |
| `version`       | Top section version (e.g. `v1.2.3+5`) |
| `date`          | Top section date (e.g. `2026-05-13`) |
| `summary_block` | Contents of `<!-- summary --> ... <!-- /summary -->` (empty until PR 2) |
| `entries_block` | Contents of `<!-- entries --> ... <!-- /entries -->` plus pending matching-version fragments |

## Read-only contract

This action never writes to the repo. All file mutation (fragment generation,
consolidation, version-section creation) happens in the consumer's pre-commit
hook (`release-notes-update`, in `hooks/release-notes-update/`).

## Breaks if

- `RELEASE_NOTES.md` is missing or contains no `## v...` sections → exits 1 with
  an error message. The expected cause: the version-bump PR did not run
  pre-commit. Re-run it locally and re-commit.
