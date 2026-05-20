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

echo "Done:"
echo "  ${PRIMARY_ROOT}/docs/urs-compiled.pdf"
echo "  ${PRIMARY_ROOT}/docs/urs-compiled.docx"
echo "  ${PRIMARY_ROOT}/docs/urs-term-index.pdf"
echo "  ${PRIMARY_ROOT}/docs/urs-term-index.docx"
