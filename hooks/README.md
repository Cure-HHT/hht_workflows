# Cure-HHT custom pre-commit hooks

Currently empty. This directory is reserved for hooks that are
specific to Cure-HHT conventions — for example, REQ-format checks
or validations driven by [elspais](https://github.com/anspar-corp/elspais)
(the requirement-traceability tool used across Cure-HHT repos to
verify that every formal requirement is referenced from code, tests,
and results). Hooks of this kind belong here rather than in a public
pre-commit-hooks repository.

When the first such hook lands, this README will document the
expected directory layout and how consumer repos reference the hooks
in their `.pre-commit-config.yaml` (typically as
`repo: https://github.com/Cure-HHT/hht_workflows` with the relevant
`hooks:` ID).
