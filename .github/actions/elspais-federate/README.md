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
| `link` | no | `'true'` | When `'false'`, clone each associate but skip running `elspais associate` (and the final `elspais associate --list`) on the host. Use this when `elspais` exists only inside a container the caller runs separately; the action prints the cloned destination paths and the caller links them itself, inside the container. |

## Notes

- Clones are shallow and sparse (`spec/` + `.elspais.toml`); application code is
  never fetched.
- Only list what your `spec/` actually cites. Omitting a needed repository fails
  loudly — `elspais checks` names the dangling reference — so the list cannot
  drift silently.
- An associate only resolves a requirement its checkout **contains**; during a
  stacked rollout a citation stays unresolved until the defining PR merges.
- `link: false` is for a consumer that runs `elspais checks` **inside a Docker
  container**, where `elspais` exists only in the image — not on the host
  runner. Clone on the host (into a path inside the container's bind mount),
  then run `elspais associate` yourself, inside the container, once it starts.

### Containerized usage (`link: false`)

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
    # Workspace-relative so the clones land inside the container's bind mount.
    workspace-parent: .elspais-associates
    link: 'false'
- run: |
    docker run --rm \
      -v "${{ github.workspace }}:/workspace" \
      -w /workspace \
      my-image:tag \
      sh -c '
        for dest in .elspais-associates/*; do
          elspais associate "$dest"
        done
        elspais checks
      '
```
