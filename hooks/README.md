# Cure-HHT custom pre-commit hooks

Currently empty. This directory is reserved for hooks that are
specific to Cure-HHT conventions (e.g., REQ-format checks,
elspais-driven validations) and not appropriate for a public
pre-commit-hooks repo.

When the first such hook lands, this README will document the
expected directory layout and how consumer repos reference the hooks
in their `.pre-commit-config.yaml` (typically as
`repo: https://github.com/Cure-HHT/hht_workflows` with the relevant
`hooks:` ID).
