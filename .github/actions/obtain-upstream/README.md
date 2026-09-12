# obtain-upstream

Materialise another repository's whole content at a pinned commit, once per run,
at a path every later step reads.

## Why it works this way

**Whole content, not a curated subset.** Nothing here selects which files count,
so no class of file can change without changing what a consumer sees. A subset
would reproduce, somewhere new, the defect of an artifact whose identity does
not move when its requirements do.

**Once per run, not once per consumer.** A stamp inside the destination records
which commit the tree holds, so a repeat request for that commit copies nothing.
Two steps reading the same path are reading the same bytes, not two copies that
happen to agree.

**A pin names one artifact or it names nothing.** The upstream publishes one
artifact per commit on its main line, tagged by that commit. A pin naming a
commit that published nothing is a hard failure: this action will not fall back
to a nearby revision, because a consumer that quietly reads one produces reports
and deliverables describing code it did not use.

Uppercase hex is refused rather than lowercased, so the pin a reviewer reads is
the pin that resolved.

**One implementation, two entry points.** The work lives in `obtain.sh`, which
this action calls and which any step obtaining several upstreams in a loop calls
too -- a composite action cannot be invoked in a loop, and a second copy of the
logic would be a second answer to what obtaining means. That covers the default
destination as well, reachable as `obtain.sh --dest-for <owner/repo> <commit>`: the stamp
only makes a repeat request a no-op if both entry points land the same pin in
the same place.

**The token arrives in the environment.** `obtain.sh` reads `TOKEN` from its
environment and passes it to `docker login` on stdin, rather than taking it as
an argument, where `set -x` and `ps` would print it.

## Inputs

| Input | Required | Default | Meaning |
| ----- | -------- | ------- | ------- |
| `repository` | yes | — | Upstream as `owner/name`. |
| `commit` | yes | — | The pinned commit: 40 lowercase hex characters. |
| `registry` | no | `ghcr.io` | Registry holding the upstream artifacts. |
| `dest` | no | `${RUNNER_TEMP}/upstream/<owner>/<name>` | Where to materialise the tree. **Whatever is at this path is replaced**, so the tree holds one commit's content rather than a merge with what was there. The default carries the owner as well as the name, so no two upstreams collide. One destination holds one repository; two registries serving the same `owner/name` in one job would collide, which nothing in this estate does. |
| `token` | yes | — | Token with read access to the upstream artifact. |

## Outputs

| Output | Meaning |
| ------ | ------- |
| `path` | Absolute path to the materialised tree. |
| `digest` | Resolved artifact digest, for the provenance record. |

The digest is recorded, never pinned against: it is derived from the commit each
time rather than maintained beside it as a second value to keep in step.

## Usage

```yaml
- id: core
  uses: Cure-HHT/hht_workflows/.github/actions/obtain-upstream@<sha>
  with:
    repository: cure-hht/hht_diary
    commit: ${{ steps.pins.outputs.core_commit }}
    token: ${{ secrets.GITHUB_TOKEN }}

- name: Read something out of it
  run: ls "${{ steps.core.outputs.path }}/spec"
```

Calling it again for the same commit — in another step, for another consumer —
returns the same `path` and `digest` without contacting the registry.

## What the upstream must provide

An image tagged `<registry>/<repository>:commit-<sha>` carrying the repository's
whole tree at `/upstream`. Publishing must be unconditional on merge to the main
line: a consumer pins a commit, so an artifact has to exist for every commit
that can be pinned, and a path-filtered publish leaves commits that cannot be
resolved.

## Tests

```sh
cd .github/actions/obtain-upstream
PYTHONPATH=. pytest tests/ -v
```

`test_materialise.py` extracts the materialise step straight out of
`action.yml` and runs it against a stub `docker`, so the test cannot drift from
the action. The no-op case is proved by the absence of a copy in the stub's call
record rather than by an exit code, which would be zero either way.
