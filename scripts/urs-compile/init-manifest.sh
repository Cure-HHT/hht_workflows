#!/usr/bin/env bash
# init-manifest.sh — seed a URS manifest in a target repo (idempotent).
#
# Usage:
#   init-manifest.sh <target-repo> [name=urs]
#
# Copies templates/urs-section-map.template.yaml to
#   <target-repo>/spec/URS-manifest/<name>.yaml
# only if that file does not already exist, then prints next steps.
#
# Running a second time with the same target is safe: the existing manifest
# is left untouched and a message is printed to stdout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/templates/urs-section-map.template.yaml"
TARGET_REPO="${1:?usage: init-manifest.sh <target-repo> [name=urs]}"
NAME="${2:-urs}"
DEST_DIR="${TARGET_REPO}/spec/URS-manifest"
DEST="${DEST_DIR}/${NAME}.yaml"

if [ -f "${DEST}" ]; then
  echo "Manifest already exists at ${DEST}; leaving it untouched."
  exit 0
fi

mkdir -p "${DEST_DIR}"
cp "${TEMPLATE}" "${DEST}"

echo "Seeded ${DEST} from the URS manifest template."
echo "Next steps:"
echo "  1. Edit ${DEST}: document identity, levels, metadata, and chapter files."
echo "  2. Add spec/URS-manifest/sources.local.yaml (gitignored) mapping source name -> local path for local compiles."
echo "  3. Run the URS compile to produce docs/${NAME}.pdf / .docx."
