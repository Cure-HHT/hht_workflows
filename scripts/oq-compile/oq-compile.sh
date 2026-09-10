#!/usr/bin/env bash
# oq-compile.sh — produce the OQ traceability deliverables.
#
# Invoke from the "primary" repo (the consumer repo holding
# spec/OQ-manifest/oq.yaml). Associate roots contribute the federated
# requirements and journeys.
#
# Usage:
#   oq-compile.sh [PRIMARY_ROOT] [ASSOCIATE_ROOT]
#
# Environment overrides:
#   PRIMARY_ROOT        Same as positional argument 1 (default: cwd).
#   ASSOCIATE_ROOT      Same as positional argument 2.
#   ASSOCIATE_ROOTS     Newline-delimited associate paths; takes precedence.
#   MANIFEST            Manifest path relative to PRIMARY_ROOT
#                       (default: spec/OQ-manifest/oq.yaml).
#   REPORTS_DIR         Committed CSV extract directory, relative to
#                       PRIMARY_ROOT (default: promotion-evidence/_reports).
#   BUILD_DIR           Run-bound artifact directory, relative to
#                       PRIMARY_ROOT (default: promotion-evidence/_build).
#   TOOL_VERSION        Generator identity for the provenance sheet. Set by
#                       the composite action to the resolved action ref;
#                       falls back to this checkout's commit SHA.
#   PYTHON              Python interpreter (default: python3).
#   ELSPAIS             elspais CLI (default: elspais).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIMARY_ROOT="${1:-${PRIMARY_ROOT:-$PWD}}"
ASSOCIATE_ROOT="${2:-${ASSOCIATE_ROOT:-}}"
MANIFEST="${MANIFEST:-spec/OQ-manifest/oq.yaml}"
REPORTS_DIR="${REPORTS_DIR:-promotion-evidence/_reports}"
BUILD_DIR="${BUILD_DIR:-promotion-evidence/_build}"
PYTHON="${PYTHON:-python3}"
ELSPAIS="${ELSPAIS:-elspais}"

PRIMARY_ROOT="$(cd "$PRIMARY_ROOT" && pwd)"

if [ ! -f "${PRIMARY_ROOT}/${MANIFEST}" ]; then
  echo "::error::manifest not found: ${PRIMARY_ROOT}/${MANIFEST}" >&2
  exit 1
fi

# Resolve associate roots: ASSOCIATE_ROOTS wins, then a single ASSOCIATE_ROOT.
declare -a ROOTS=()
if [ -n "${ASSOCIATE_ROOTS:-}" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] && ROOTS+=("$line")
  done <<< "$ASSOCIATE_ROOTS"
elif [ -n "$ASSOCIATE_ROOT" ]; then
  ROOTS+=("$ASSOCIATE_ROOT")
fi

for root in "${ROOTS[@]:-}"; do
  [ -z "$root" ] && continue
  if [ ! -d "$root" ]; then
    echo "::error::associate root is not a directory: ${root}" >&2
    exit 1
  fi
  abs="$(cd "$root" && pwd)"
  echo "federating associate: ${abs}"
  (cd "$PRIMARY_ROOT" && "$ELSPAIS" associate "$abs")
done

WORK="${PRIMARY_ROOT}/${BUILD_DIR}/oq"
mkdir -p "$WORK"

SCOPE="$("$PYTHON" -c "import sys,yaml;print(yaml.safe_load(open(sys.argv[1]))['scope'])" \
  "${PRIMARY_ROOT}/${MANIFEST}")"

# The values are named explicitly instead of selecting `--dimension uat`.
# That dimension suppresses the `verified` and `tested` figures, which are the
# only source for the requirement sheet's test-result column; asking for the
# values by name yields both kinds of evidence in one export.
echo "exporting trace for scope: ${SCOPE}"
(cd "$PRIMARY_ROOT" && "$ELSPAIS" trace \
  --scope "$SCOPE" \
  --values id,title,level,status,verified,tested,uat_verified,journeys \
  --format json \
  -o "${WORK}/trace.json")

echo "exporting graph"
(cd "$PRIMARY_ROOT" && "$ELSPAIS" graph -o "${WORK}/graph.json")

ELSPAIS_VERSION="$("$ELSPAIS" --version | head -1)"
# A fresh checkout (e.g. the readiness fixture, `git init`-ed but never
# committed) has no HEAD. The report is still producible without a commit
# SHA to stamp, so this states an explicit "unknown" rather than aborting —
# unlike the associate/federation steps above, where failure means the
# report itself would be wrong.
PRIMARY_COMMIT="$(git -C "$PRIMARY_ROOT" rev-parse HEAD 2>/dev/null)" || PRIMARY_COMMIT="unknown"

# TOOL_VERSION identifies the generator on the provenance sheet. A remote
# `uses:` unpacks this action as a tarball with no .git, so the git derivation
# below resolves to "unknown" for every consumer run — precisely the runs whose
# provenance matters. The caller therefore passes the ref it resolved
# (github.action_ref) in TOOL_VERSION, and `:-` treats the empty string a local
# `uses: ./` yields as unset so a working tree still stamps its own commit.
if [ -z "${TOOL_VERSION:-}" ]; then
  TOOL_VERSION="$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null)" || TOOL_VERSION="unknown"
fi

# Name an associate by something intrinsic to the repository, so a reader of
# the provenance sheet can tell which repository a commit belongs to. The
# checkout directory name is not that: it is whatever the caller cloned into
# (a branch-named worktree, a runner temp path). Preference order: the elspais
# project identity the associate declares, then its git remote, then — only
# when the tree states neither — the directory name.
associate_identity() {
  local root="$1" ident=""
  if [ -f "${root}/.elspais.toml" ]; then
    # An associate whose config is unreadable or has no [project] table falls
    # through to the git remote below; it is not a reason to abort the report.
    if ! ident="$("$PYTHON" - "$root/.elspais.toml" <<'PYEOF' 2>/dev/null
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
with open(sys.argv[1], "rb") as handle:
    project = tomllib.load(handle).get("project") or {}
print(project.get("namespace") or project.get("name") or "")
PYEOF
)"; then
      ident=""
    fi
  fi
  if [ -z "$ident" ]; then
    ident="$(git -C "$root" config --get remote.origin.url 2>/dev/null)" || ident=""
    # Reduce a remote URL to owner/repo; both SSH and HTTPS forms end that way.
    ident="${ident%.git}"
    ident="${ident##*:}"
    if [ -n "$ident" ]; then
      ident="$(echo "$ident" | awk -F/ 'NF>1{print $(NF-1)"/"$NF; next}{print $NF}')"
    fi
  fi
  if [ -z "$ident" ]; then
    ident="$(basename "$root")"
  fi
  printf '%s' "$ident"
}

declare -a ASSOC_ARGS=()
for root in "${ROOTS[@]:-}"; do
  [ -z "$root" ] && continue
  sha="$(git -C "$root" rev-parse HEAD 2>/dev/null)" || sha="unknown"
  ASSOC_ARGS+=(--associate-commit "$(associate_identity "$root")@${sha}")
done

declare -a CMD=(
  "$PYTHON" "${SCRIPT_DIR}/compile-oq.py"
  --manifest "${PRIMARY_ROOT}/${MANIFEST}"
  --trace "${WORK}/trace.json"
  --graph "${WORK}/graph.json"
  --out-csv-dir "${PRIMARY_ROOT}/${REPORTS_DIR}"
  --out-xlsx "${PRIMARY_ROOT}/${BUILD_DIR}/oq-report.xlsx"
  --primary-root "$PRIMARY_ROOT"
  --primary-commit "$PRIMARY_COMMIT"
  --elspais-version "$ELSPAIS_VERSION"
  --tool-version "$TOOL_VERSION"
)
if [ "${#ASSOC_ARGS[@]}" -gt 0 ]; then
  CMD+=("${ASSOC_ARGS[@]}")
fi
"${CMD[@]}"
