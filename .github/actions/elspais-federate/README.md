# elspais-federate

Links the Cure-HHT repositories this repo *cites* as elspais **associates**, so
cross-repo requirement citations (`Refines:`, `Integrates:`) resolve when
`elspais checks` runs. Without it those citations fail `spec.broken_references`,
which is error-level and is **not** suppressed by `--lenient`.

Implements `HHT-OPS-repo-bootstrap/I`.

## Usage

```yaml
- uses: actions/create-github-app-token@v1
  id: app-token
  with:
    app-id: ${{ vars.OPS_BOT_APP_ID }}
    private-key: ${{ secrets.OPS_BOT_PRIVATE_KEY }}
    owner: Cure-HHT
    repositories: hht_admin,event_sourcing
- uses: Cure-HHT/hht_workflows/.github/actions/elspais-federate@<commit-sha>
  with:
    associates: |
      Cure-HHT/hht_admin
      Cure-HHT/event_sourcing
    token: ${{ steps.app-token.outputs.token }}
- run: elspais checks
```

## Inputs

| Input | Required | Default | Meaning |
| --- | --- | --- | --- |
| `associates` | yes | — | Newline-separated `owner/repo`. Blank lines and `#` comments allowed. |
| `token` | yes | — | Per-job App token, `contents: read`, scoped to exactly these repos, ≤1h. |
| `ref` | no | `''` | Ref to check each associate out at. Empty = default branch. |
| `workspace-parent` | no | `..` | Where associates are cloned, as siblings of this checkout. |

## Notes

- Clones are shallow and sparse (`spec/` + `.elspais.toml`); application code is
  never fetched.
- Only list what your `spec/` actually cites. Omitting a needed repository fails
  loudly — `elspais checks` names the dangling reference — so the list cannot
  drift silently.
- An associate only resolves a requirement its checkout **contains**; during a
  stacked rollout a citation stays unresolved until the defining PR merges.
