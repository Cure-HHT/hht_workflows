#!/bin/sh
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
hht_hooks_guard "$REPO_ROOT" ".githooks" "scripts/setup.sh" "scripts/setup.sh --check"

# Implements: HHT-OPS-repo-bootstrap/I
hht_associates_guard "$REPO_ROOT"

# The test target directories, listed once.
TARGETS='hooks/release-notes-update/tests
hooks/no-or-true-guard/tests
hooks/confidential-terms-scan/tests
.github/actions/release-notes-publish/tests
.github/actions/sponsor-base-preflight/tests
.github/actions/elspais-federate/tests
bootstrap/tests'

if [ "${1:-}" = "--list" ]; then
  echo "$TARGETS"
  exit 0
fi

# setup.sh installs the package; the [test] extra (pytest, PyYAML) is what the
# suite needs on top.
python3 -m pip install --quiet -e '.[test]'

# The three hook suites share the default path; the two action suites each need
# their own PYTHONPATH, exactly as release-notes-tests.yml runs them.
pytest hooks/release-notes-update/tests/ \
       hooks/no-or-true-guard/tests/ \
       hooks/confidential-terms-scan/tests/

( cd .github/actions/release-notes-publish && \
  PYTHONPATH=.:../../../hooks/release-notes-update pytest tests/ )

( cd .github/actions/sponsor-base-preflight && \
  PYTHONPATH=. pytest tests/ )

( cd .github/actions/elspais-federate && \
  PYTHONPATH=. pytest tests/ )

pytest bootstrap/tests/
