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
#   ASSOCIATE_ROOT      Same as positional argument 2 (back-compat single
#                       associate; ignored when ASSOCIATE_ROOTS is set).
#   ASSOCIATE_ROOTS     Newline-delimited list of associate source paths
#                       (multi-source; takes precedence over ASSOCIATE_ROOT
#                       and sources.local.yaml).
#   MANIFEST            Path to the URS manifest YAML, relative to PRIMARY_ROOT
#                       (default: spec/URS-manifest/urs.yaml).
#   OUTPUT_BASENAME     Override the output filename stem (default: manifest
#                       filename without .yaml extension, e.g. "urs" from
#                       "urs.yaml"). Affects all four deliverable filenames.
#   PYTHON              Python interpreter (default: python3).
#   ELSPAIS             elspais CLI (default: elspais).
#
# Associate sources are resolved in this order (first non-empty wins):
#   1. ASSOCIATE_ROOTS env — newline-delimited paths, blank lines skipped.
#   2. ASSOCIATE_ROOT env / positional arg 2 — back-compat single path.
#   3. ${PRIMARY_ROOT}/spec/URS-manifest/sources.local.yaml — gitignored
#      "name: path" YAML map; values are used as source paths.
#   4. No associates — single-source build.
#
# Each resolved associate root is validated (must be an existing directory)
# then wired into the elspais federation via `elspais associate <abs-path>`
# before `elspais graph`. The FIRST associate is also passed to compile-urs.py
# as --associate-root (prose fallback + resource-path). Build provenance tracks
# only the first associate; multi-source provenance is out of scope for this
# task.
#
# The script:
#   1. Resolves and validates associate sources, wires each into elspais.
#   2. Runs `elspais graph` from PRIMARY_ROOT to emit a federated graph
#      JSON. PRIMARY_ROOT's elspais config declares associates (typically
#      via the gitignored .elspais.local.toml) so the graph aggregates
#      all repos' REQs.
#   3. Runs `elspais glossary` and `elspais term-index` from PRIMARY_ROOT
#      to emit federated glossary and term index markdown.
#   4. Invokes compile-urs.py, which reads sponsor identity from
#      PRIMARY_ROOT/spec/URS-manifest/sponsor-info.yaml, generates a
#      LaTeX include-in-header overriding the template's sponsor macros,
#      assembles the markdown, and runs pandoc once per format.
#   5. Emits a stand-alone term-index PDF + DOCX alongside the URS body.
#   6. Writes docs/<name>-build-provenance.md stamping the out-of-repo input
#      versions (this pipeline's `git describe` and the associate repo's
#      HEAD) the deliverables were generated from. The consumer repo does
#      not version-pin this pipeline, so this is the only record tying a
#      committed deliverable to the scripts + source that produced it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --init: delegate to init-manifest.sh, then exit. This early-exit runs
# before manifest resolution so --init works on repos that have no manifest yet.
if [ "${1:-}" = "--init" ]; then
  shift
  TARGET="${1:-$(pwd)}"
  NAME_ARG="${2:-}"
  exec "${SCRIPT_DIR}/init-manifest.sh" "${TARGET}" ${NAME_ARG:+"${NAME_ARG}"}
fi

PRIMARY_ROOT="${1:-${PRIMARY_ROOT:-$(pwd)}}"
PRIMARY_ROOT="$(cd "$PRIMARY_ROOT" && pwd)"
ASSOCIATE_ROOT="${2:-${ASSOCIATE_ROOT:-}}"
PYTHON="${PYTHON:-python3}"
ELSPAIS="${ELSPAIS:-elspais}"

# Manifest resolution — required; hard-fail with a seeding hint if absent.
MANIFEST="${MANIFEST:-spec/URS-manifest/urs.yaml}"
MANIFEST_PATH="${PRIMARY_ROOT}/${MANIFEST}"
if [ ! -f "${MANIFEST_PATH}" ]; then
  echo "error: manifest not found at ${MANIFEST_PATH}." >&2
  echo "       Seed one with: ${SCRIPT_DIR}/init-manifest.sh ${PRIMARY_ROOT}" >&2
  exit 1
fi
NAME="${OUTPUT_BASENAME:-$(basename "${MANIFEST%.yaml}")}"

# Associate source resolution (precedence: ASSOCIATE_ROOTS > ASSOCIATE_ROOT >
# sources.local.yaml > none).
SOURCES_LOCAL="${PRIMARY_ROOT}/spec/URS-manifest/sources.local.yaml"
declare -a ASSOC_ROOTS=()

if [ -n "${ASSOCIATE_ROOTS:-}" ]; then
  # Newline-delimited list from env; skip blank lines.
  while IFS= read -r _line; do
    [ -z "${_line}" ] && continue
    ASSOC_ROOTS+=("${_line}")
  done <<< "${ASSOCIATE_ROOTS}"
elif [ -n "${ASSOCIATE_ROOT:-}" ]; then
  # Back-compat single associate (positional arg 2 / env).
  ASSOC_ROOTS+=("${ASSOCIATE_ROOT}")
elif [ -f "${SOURCES_LOCAL}" ]; then
  # Parse values from a "name: path" YAML map.
  while IFS= read -r _line; do
    [ -z "${_line}" ] && continue
    ASSOC_ROOTS+=("${_line}")
  done < <("${PYTHON}" -c \
    'import yaml,sys; d=yaml.safe_load(open(sys.argv[1])) or {}; print("\n".join(str(v) for v in d.values()))' \
    "${SOURCES_LOCAL}")
fi

# Validate each source, resolve to absolute, wire into elspais federation.
declare -a ABS_ASSOC_ROOTS=()
if [ ${#ASSOC_ROOTS[@]} -gt 0 ]; then
  for _root in "${ASSOC_ROOTS[@]}"; do
    if [ ! -d "${_root}" ]; then
      echo "error: associate source path not found: ${_root}" >&2
      exit 1
    fi
    _abs="$(cd "${_root}" && pwd)"
    ABS_ASSOC_ROOTS+=("${_abs}")
    (cd "${PRIMARY_ROOT}" && "${ELSPAIS}" associate "${_abs}")
  done
fi

# Back-compat: ASSOCIATE_ROOT = first resolved associate (for --associate-root
# PY_ARG, provenance, and pandoc resource-path). Provenance tracks only the
# first associate; multi-source provenance is out of scope.
ASSOCIATE_ROOT="${ABS_ASSOC_ROOTS[0]:-}"

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
#    bundled defaults for --template from its own directory; --manifest,
#    --cover, and --sponsor-info come from PRIMARY_ROOT's spec/URS-manifest/.
PY_ARGS=(
  --manifest "${MANIFEST_PATH}"
  --graph "${PRIMARY_ROOT}/build/graph.json"
  --output-md "${PRIMARY_ROOT}/build/urs-assembled.md"
  --output-pdf "${PRIMARY_ROOT}/docs/${NAME}.pdf"
  --output-docx "${PRIMARY_ROOT}/docs/${NAME}.docx"
  --cover "${PRIMARY_ROOT}/spec/URS-manifest/urs-cover.tex"
  --sponsor-info "${PRIMARY_ROOT}/spec/URS-manifest/sponsor-info.yaml"
)
if [ -n "${ASSOCIATE_ROOT:-}" ]; then
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
  -o "${PRIMARY_ROOT}/docs/${NAME}-term-index.pdf" \
  --pdf-engine xelatex \
  --template "${SCRIPT_DIR}/urs-template.latex" \
  --variable=cover-tex:"${PRIMARY_ROOT}/spec/URS-manifest/urs-term-index-cover.tex" \
  --toc --toc-depth=1 \
  --top-level-division=chapter \
  "${HEADER_ARG[@]}"
pandoc "${PRIMARY_ROOT}/build/_generated/term-index.md" \
  -o "${PRIMARY_ROOT}/docs/${NAME}-term-index.docx"

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

PROVENANCE="${PRIMARY_ROOT}/docs/${NAME}-build-provenance.md"
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

The URS deliverables in this directory (\`${NAME}.pdf\`, \`${NAME}.docx\`,
\`${NAME}-term-index.pdf\`, \`${NAME}-term-index.docx\`) are committed artifacts produced by
a local compile run using the external URS compile pipeline, which the consumer
repo does not version-pin. This file records the versions of the out-of-repo
inputs the current deliverables were generated from.

## Current deliverables

Built: ${BUILD_DATE}

| Input | Repo | Version |
| :---- | :---- | :---- |
| URS compile scripts (\`scripts/urs-compile/\`) | \`${WF_SLUG}\` (external) | \`${WF_VERSION}\` |
EOF

  if [ -n "${ASSOCIATE_ROOT:-}" ]; then
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
echo "  ${PRIMARY_ROOT}/docs/${NAME}.pdf"
echo "  ${PRIMARY_ROOT}/docs/${NAME}.docx"
echo "  ${PRIMARY_ROOT}/docs/${NAME}-term-index.pdf"
echo "  ${PRIMARY_ROOT}/docs/${NAME}-term-index.docx"
echo "  ${PRIMARY_ROOT}/docs/${NAME}-build-provenance.md"
