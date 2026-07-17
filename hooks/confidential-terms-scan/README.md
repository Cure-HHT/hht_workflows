# confidential-terms-scan

**Why this exists:** `HHT-OPS-confidential-keywords-scrubbing/C,D` — block
project-confidential terms from entering repos where they do not belong,
across four surfaces: added content lines, file basenames, path segments of
added/renamed paths, and PR metadata (title, body, branch name). The term
list is fetched at scan time from the consumer's admin-owned `scan-*`
Doppler project; it is never committed, written to disk, echoed, or logged.

## Surfaces and enforcement points

```text
  surface          pre-push (this hook)      PR CI (composite action)
  content lines    yes                       yes
  file basenames   yes                       yes
  path segments    yes                       yes
  branch name      yes                       yes
  PR title/body    no (does not exist yet)   yes (open/synchronize/edited)
```

## Consumer wiring (pre-push)

This hook's `stages` is `pre-push`; it only runs if the consumer repo has
pre-push hooks installed. `pre-commit install` alone (the default, hook-type
`pre-commit`) does not install it — run
`pre-commit install --hook-type pre-push` as well, or set
`default_install_hook_types: [pre-commit, pre-push]` in the consumer's
`.pre-commit-config.yaml` so a plain `pre-commit install` covers both.

```yaml
# .pre-commit-config.yaml
default_install_hook_types: [pre-commit, pre-push]
repos:
  - repo: https://github.com/Cure-HHT/hht_workflows
    rev: <tag>
    hooks:
      - id: confidential-terms-scan
        args: [--doppler-project=scan-<consumer>, --on-fetch-error=warn]
```

`--on-fetch-error=warn` degrades to a loud warning when the developer's
doppler CLI cannot read the `scan-*` project (PR CI remains the
authoritative gate). The default is `fail`.

## Allowances

`.confidential-terms-allow` in the consumer repo root: path globs (one per
line, `#` comments). Matching paths are exempt from all surfaces. The file
holds paths only — never terms — and should be CODEOWNERS-protected.

## Report format

Counts, `file:line` locations, masked paths (`***` replaces a matching
segment), and PR-metadata field names. Matched text is never printed.

## Triage doctrine — hygiene guard, not secrecy

The prohibit lists include sponsor id tokens (and a short hyphenated
sponsor prefix). These are listed not because the ids are secret — they
appear in repo names by design — but as a guard against mistakes: there is
no legitimate reason for one sponsor's literal to appear in another repo's
code, config, or docs, so a hit means cross-tenant leakage
(`HHT-OPS-sponsor-name-is-data`). Triage every hit by asking "should this
reference exist here at all?", never "is this string secret?". Do not
remove ids from the list on "it's not secret" grounds. Remediate with a
placeholder (e.g. `<sponsor-configured>`), a rewording, or — deliberately,
with review — an `.confidential-terms-allow` entry.
