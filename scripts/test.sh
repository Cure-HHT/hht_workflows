#!/bin/bash
# Run this repo's automated test suite, or resolve its test targets with --list.
#
# The suites mirror the ones CI runs in
# .github/workflows/release-notes-tests.yml — that workflow is a required check,
# so keep the two in step when adding a suite.
#
# Implements: HHT-OPS-repo-bootstrap/C
set -e

cd "$(git rev-parse --show-toplevel)"
REPO_ROOT="$(pwd)"

# Warn (do not fail) a developer whose clone's hooks are inert. Silent under CI.
# Implements: HHT-OPS-repo-bootstrap/F
. "$REPO_ROOT/bootstrap/hooks-guard.sh"
hht_hooks_guard "$REPO_ROOT" ".githooks" "tools/setup-repo.sh" "tools/setup-repo.sh --check"

# Implements: HHT-OPS-repo-bootstrap/I
hht_associates_guard "$REPO_ROOT"

# The test target directories, listed once.
#
# scripts/urs-compile/test_compile_urs is deliberately absent: it needs the
# pinned pandoc and a LaTeX engine, which CI installs for that job and a clone
# does not have. Every other suite CI runs belongs here.
TARGETS='hooks/release-notes-update/tests
hooks/no-or-true-guard/tests
hooks/confidential-terms-scan/tests
.github/actions/release-notes-publish/tests
.github/actions/sponsor-base-preflight/tests
.github/actions/elspais-federate/tests
.github/actions/obtain-upstream/tests
.github/actions/build-urs/tests
.github/actions/cosign-verify/tests
scripts/publish/tests
.github/actions/cloud-run-resolve-serving-digest/tests
tests/test_promote_template.py
bootstrap/tests'

if [ "${1:-}" = "--list" ]; then
  echo "$TARGETS"
  exit 0
fi

# setup.sh installs the package; the [test] extra (pytest, PyYAML) is what the
# suite needs on top.
python3 -m pip install --quiet -e '.[test]'

# One pytest per target, driven from the list above so the two cannot disagree:
# a target named there is a target that runs. Several hooks name their test
# package `tests`, so a single invocation spanning them fails collection on the
# duplicate module name and runs none of them.
#
# Two suites import a module from their own directory and so run from it, with
# that directory on the path. Anything else runs from the repository root.
echo "$TARGETS" | while IFS= read -r target; do
  [ -z "$target" ] && continue
  case "$target" in
    .github/actions/release-notes-publish/tests)
      ( cd .github/actions/release-notes-publish && \
        PYTHONPATH=.:../../../hooks/release-notes-update pytest tests/ ) ;;
    .github/actions/sponsor-base-preflight/tests|\
    .github/actions/elspais-federate/tests|\
    .github/actions/obtain-upstream/tests)
      ( cd "$(dirname "$target")" && PYTHONPATH=. pytest tests/ ) ;;
    *)
      pytest "$target" ;;
  esac
done
