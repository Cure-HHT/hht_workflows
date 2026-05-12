# Branch protection (hht_workflows)

The `main` branch of `Cure-HHT/hht_workflows` MUST have the following
protection rules. They are intentionally documented here (not encoded in
Terraform) because this repo is the bootstrap for the composite-action
library — managing its own protection from a Terraform consumer would
create a circular dependency.

## Required settings

- Require a pull request before merging
  - Require approvals: 1
  - Dismiss stale approvals on new commits: enabled
  - Require review from Code Owners: enabled
- Require status checks to pass before merging
  - Required checks: one entry per job in `readiness-checks.yml`, by exact `workflow-name / job-name`:
    - `Readiness Checks / gcp-wif-auth` (real WIF handshake readiness check)
    - `Readiness Checks / no-op` (placeholder; replace with real jobs as PR -1.2 and -1.3 add them)
- Require conversation resolution before merging: enabled
- Enforce all the above settings on admins: enabled (`enforce_admins=true`)
- Push restrictions: not used. The require-a-pull-request rule already prevents
  direct pushes to `main` by non-admins; combined with `enforce_admins=true`,
  even admins must go through PR review. An explicit push-restriction list
  becomes useful only with a larger team than this repo currently has.

## How to apply

Apply via GitHub UI (Settings -> Branches -> Add rule) or via gh CLI.

Note: `gh api` `-F` flags require bracket notation for nested JSON keys.
Dot-notation (`a.b=value`) is sent as a literal flat key and silently
ignored by the GitHub API.

    gh api -X PUT repos/Cure-HHT/hht_workflows/branches/main/protection \
      -F 'required_pull_request_reviews[required_approving_review_count]=1' \
      -F 'required_pull_request_reviews[require_code_owner_reviews]=true' \
      -F 'required_pull_request_reviews[dismiss_stale_reviews]=true' \
      -F 'required_status_checks[strict]=true' \
      -F 'required_status_checks[contexts][]=Readiness Checks / gcp-wif-auth' \
      -F 'required_status_checks[contexts][]=Readiness Checks / no-op' \
      -F required_conversation_resolution=true \
      -F enforce_admins=true \
      -F restrictions=null

The `contexts[]` entry must match the exact check name GitHub reports
for each required job, which has the form `workflow-name / job-name`.
As jobs are added (PR -1.2 adds `gcp-wif-auth`, PR -1.3 adds
`doppler-oidc-auth`), append more `-F 'required_status_checks[contexts][]=...'`
entries.

## Why not Terraform

Managing this repo's protection from `hht_admin/terraform` would require
`hht_admin` to be set up first, then `hht_workflows` to be set up, then
back to `hht_admin` to apply protection. Since `hht_admin` consumes from
`hht_workflows` (composite actions), this creates a bootstrap cycle.

Encoding the rules in markdown is the simpler answer: the rules are
checked into the repo they govern, applied once via gh CLI, and the
review history is in git.
