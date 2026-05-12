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
  - Required checks:
    - `Smoke test composite actions / *` (every job in smoke-test-actions.yml)
- Require conversation resolution before merging: enabled
- Do not allow bypassing the above settings: enabled
- Restrict pushes that create matching branches: enabled (only admins)

## How to apply

Apply via GitHub UI (Settings -> Branches -> Add rule) or via gh CLI:

    gh api -X PUT repos/Cure-HHT/hht_workflows/branches/main/protection \
      -F required_pull_request_reviews.required_approving_review_count=1 \
      -F required_pull_request_reviews.require_code_owner_reviews=true \
      -F required_pull_request_reviews.dismiss_stale_reviews=true \
      -F required_status_checks.strict=true \
      -F required_status_checks.contexts[]="Smoke test composite actions" \
      -F required_conversation_resolution=true \
      -F enforce_admins=false \
      -F restrictions=null

(Adjust the contexts list as jobs are added by PR -1.2 and PR -1.3.)

## Why not Terraform

Managing this repo's protection from `hht_admin/terraform` would require
`hht_admin` to be set up first, then `hht_workflows` to be set up, then
back to `hht_admin` to apply protection. Since `hht_admin` consumes from
`hht_workflows` (composite actions), this creates a bootstrap cycle.

Encoding the rules in markdown is the simpler answer: the rules are
checked into the repo they govern, applied once via gh CLI, and the
review history is in git.
