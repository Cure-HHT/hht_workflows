#!/usr/bin/env bash
# compile-urs.sh — produce the URS PDF + DOCX deliverables.
#
# This script is the local-dev / CI entrypoint for the URS compile pipeline.
# Invoke it from the "primary" repo (the consumer repo holding the
# spec/URS-manifest/ content); the script auto-detects script-relative
# defaults and forwards consumer-supplied paths to compile-urs.py.
#
# Usage:
#   compile-urs.sh [PRIMARY_ROOT] [ASSOCIATE_ROOT]
#
# PRIMARY_ROOT defaults to the current working directory.
# ASSOCIATE_ROOT (optional) is the sibling repo's worktree contributing
# cross-referenced spec content and images via the federated elspais graph
# and pandoc's --resource-path fallback.
#
# Environment overrides:
#   PRIMARY_ROOT        Same as positional argument 1.
#   ASSOCIATE_ROOT      Same as positional argument 2.
#   PYTHON              Python interpreter (default: python3).
#   ELSPAIS             elspais CLI (default: elspais).
#
# The script:
#   1. Runs `elspais graph` from PRIMARY_ROOT to emit a federated graph
#      JSON. PRIMARY_ROOT's elspais config declares ASSOCIATE_ROOT as an
#      associate (typically via a gitignored .elspais.local.toml) so the
#      graph aggregates both repos' REQs.
#   2. Runs `elspais glossary` and `elspais term-index` from PRIMARY_ROOT
#      to emit federated glossary and term index markdown.
#   3. Invokes compile-urs.py, which reads sponsor identity from
#      PRIMARY_ROOT/spec/URS-manifest/sponsor-info.yaml, generates a
#      LaTeX include-in-header overriding the template's sponsor macros,
#      assembles the markdown, and runs pandoc once per format.
#   4. Emits a stand-alone term-index PDF + DOCX alongside the URS body.
#   5. Writes docs/urs-build-provenance.md stamping the out-of-repo input
#      versions (this pipeline's `git describe` and the associate repo's
#      HEAD) the deliverables were generated from. The consumer repo does
#      not version-pin this pipeline, so this is the only record tying a
#      committed deliverable to the scripts + source that produced it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIMARY_ROOT="${1:-${PRIMARY_ROOT:-$(pwd)}}"
PRIMARY_ROOT="$(cd "$PRIMARY_ROOT" && pwd)"
ASSOCIATE_ROOT="${2:-${ASSOCIATE_ROOT:-}}"
PYTHON="${PYTHON:-python3}"
ELSPAIS="${ELSPAIS:-elspais}"

mkdir -p "${PRIMARY_ROOT}/build/_generated"

# 1) Federated graph JSON.
(cd "${PRIMARY_ROOT}" && "${ELSPAIS}" graph -o "${PRIMARY_ROOT}/build/graph.json")

# 2) Federated glossary + term-index. The bare `elspais glossary` /
#    `elspais term-index` commands write markdown to stdout regardless of
#    config; redirect to the target files.
(cd "${PRIMARY_ROOT}" && "${ELSPAIS}" glossary --format markdown) \
  > "${PRIMARY_ROOT}/build/_generated/glossary.md"
(cd "${PRIMARY_ROOT}" && "${ELSPAIS}" term-index --format markdown) \
  > "${PRIMARY_ROOT}/build/_generated/term-index.md"

# 3) URS body via the Python orchestrator. compile-urs.py picks up
#    bundled defaults for --template and --manifest from its own directory;
#    --cover and --sponsor-info come from PRIMARY_ROOT's spec/URS-manifest/.
PY_ARGS=(
  --graph "${PRIMARY_ROOT}/build/graph.json"
  --output-md "${PRIMARY_ROOT}/build/urs-assembled.md"
  --output-pdf "${PRIMARY_ROOT}/docs/urs-compiled.pdf"
  --output-docx "${PRIMARY_ROOT}/docs/urs-compiled.docx"
  --cover "${PRIMARY_ROOT}/spec/URS-manifest/urs-cover.tex"
  --sponsor-info "${PRIMARY_ROOT}/spec/URS-manifest/sponsor-info.yaml"
)
if [ -n "${ASSOCIATE_ROOT}" ]; then
  ASSOCIATE_ROOT="$(cd "${ASSOCIATE_ROOT}" && pwd)"
  PY_ARGS+=(--associate-root "${ASSOCIATE_ROOT}")
fi
(cd "${PRIMARY_ROOT}" && "${PYTHON}" "${SCRIPT_DIR}/compile-urs.py" "${PY_ARGS[@]}")

# 4) Stand-alone Term Index PDF + DOCX. The federated term-index is too
#    large to bundle with the URS body (~200 extra pages, one entry per
#    indexed term with verbatim references) but is still a regulated
#    deliverable; ship it as a sibling file.
#
#    Sponsor identity is injected via the same include-in-header file
#    compile-urs.py wrote (build/sponsor-header.tex).
SPONSOR_HEADER="${PRIMARY_ROOT}/build/sponsor-header.tex"
if [ -f "${SPONSOR_HEADER}" ]; then
  HEADER_ARG=(--include-in-header "${SPONSOR_HEADER}")
else
  HEADER_ARG=()
fi
pandoc "${PRIMARY_ROOT}/build/_generated/term-index.md" \
  -o "${PRIMARY_ROOT}/docs/urs-term-index.pdf" \
  --pdf-engine xelatex \
  --template "${SCRIPT_DIR}/urs-template.latex" \
  --variable=cover-tex:"${PRIMARY_ROOT}/spec/URS-manifest/urs-term-index-cover.tex" \
  --toc --toc-depth=1 \
  --top-level-division=chapter \
  "${HEADER_ARG[@]}"
pandoc "${PRIMARY_ROOT}/build/_generated/term-index.md" \
  -o "${PRIMARY_ROOT}/docs/urs-term-index.docx"

# 5) Build-provenance record. Stamp the out-of-repo input versions alongside
#    the committed deliverables. Versions are derived from git so the script
#    stays sponsor-agnostic (no repo names baked in).
git_slug() {
  # owner/repo from the origin remote, falling back to the toplevel dirname.
  local url
  url="$(git -C "$1" remote get-url origin 2>/dev/null || true)"
  if [ -n "${url}" ]; then
    printf '%s\n' "${url%.git}" | sed -E 's#^.*[/:]([^/]+/[^/]+)$#\1#'
  else
    basename "$(git -C "$1" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$1")"
  fi
}

PROVENANCE="${PRIMARY_ROOT}/docs/urs-build-provenance.md"
WF_SLUG="$(git_slug "${SCRIPT_DIR}")"
WF_VERSION="$(git -C "${SCRIPT_DIR}" describe --tags --always --dirty 2>/dev/null || echo unknown)"
BUILD_DATE="$(date -u +%Y-%m-%d)"
PANDOC_VERSION="$(pandoc --version 2>/dev/null | head -1 || true)"
XETEX_VERSION="$(xelatex --version 2>/dev/null | head -1 || true)"

{
  cat <<EOF
# URS Build Provenance

_Generated by \`${WF_SLUG}/scripts/urs-compile/compile-urs.sh\` — do not edit by
hand; rerun the compile to refresh._

The URS deliverables in this directory (\`urs-compiled.pdf\`, \`urs-compiled.docx\`,
\`urs-term-index.pdf\`, \`urs-term-index.docx\`) are committed artifacts produced by
a local compile run using the external URS compile pipeline, which the consumer
repo does not version-pin. This file records the versions of the out-of-repo
inputs the current deliverables were generated from.

## Current deliverables

Built: ${BUILD_DATE}

| Input | Repo | Version |
| :---- | :---- | :---- |
| URS compile scripts (\`scripts/urs-compile/\`) | \`${WF_SLUG}\` (external) | \`${WF_VERSION}\` |
EOF

  if [ -n "${ASSOCIATE_ROOT}" ]; then
    ASSOC_SLUG="$(git_slug "${ASSOCIATE_ROOT}")"
    ASSOC_VERSION="$(git -C "${ASSOCIATE_ROOT}" describe --tags --always --dirty 2>/dev/null \
      || git -C "${ASSOCIATE_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    # shellcheck disable=SC2016  # literal backticks in the printf format; %s are args
    printf '| Associate spec source | `%s` (external) | `%s` |\n' "${ASSOC_SLUG}" "${ASSOC_VERSION}"
  fi

  cat <<EOF

The primary (consumer-repo) spec version is intentionally omitted: it is the
commit that adds these deliverables, so its SHA is not yet known when this file
is written, and it is implicit in that repo's own history regardless.

Tooling: ${PANDOC_VERSION}, ${XETEX_VERSION}.
EOF
} > "${PROVENANCE}"

echo "Done:"
echo "  ${PRIMARY_ROOT}/docs/urs-compiled.pdf"
echo "  ${PRIMARY_ROOT}/docs/urs-compiled.docx"
echo "  ${PRIMARY_ROOT}/docs/urs-term-index.pdf"
echo "  ${PRIMARY_ROOT}/docs/urs-term-index.docx"
echo "  ${PRIMARY_ROOT}/docs/urs-build-provenance.md"
