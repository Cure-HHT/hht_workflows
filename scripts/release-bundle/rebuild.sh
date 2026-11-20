#!/usr/bin/env bash
# rebuild.sh -- prove a release's evidence bundle complete by rebuilding its
# deliverables from nothing but the bundle, with no network.
#
# Usage:
#   rebuild.sh BUNDLE_DIR VERDICT_FILE
#
# 1. The bundle is checked against its MANIFEST: a file missing, altered or
#    unlisted stops here, before anything runs.
# 2. The toolchain is loaded from the bundle's own toolchain/image.tar, and the
#    loaded image must be the one the manifest names (image-id). Nothing is
#    pulled: an image fetched from a registry would prove the registry, not
#    the bundle.
# 3. The bundle's `rebuild` runs inside that image with --network none, the
#    bundle mounted read-only, under the manifest's SOURCE_DATE_EPOCH, writing
#    to an empty directory. Denying the network is the only way to show the
#    bundle does not reach outside itself.
# 4. bundle.py compare writes the verdict. This script exits 0 when a verdict
#    was written, whatever it says: refusing is `bundle.py admit`'s job, so a
#    failed rebuild still leaves its evidence.
#
# Run it on a host that holds nothing of the estate -- a fresh runner, not the
# one that assembled the bundle -- so a file the bundle forgot cannot be found
# lying around.
#
# Environment:
#   DOCKER   docker CLI (default: docker)
#   PYTHON   Python interpreter (default: python3)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER="${DOCKER:-docker}"
PYTHON="${PYTHON:-python3}"

if [ "$#" -ne 2 ]; then
  echo "usage: $0 BUNDLE_DIR VERDICT_FILE" >&2
  exit 2
fi
BUNDLE="$(cd "$1" && pwd)"
VERDICT="$2"

"$PYTHON" "${HERE}/bundle.py" verify --bundle "$BUNDLE"

field() {
  sed -n "s/^$1: //p" "${BUNDLE}/MANIFEST" | head -1
}
IMAGE_ID="$(field image-id)"
EPOCH="$(field source-date-epoch)"
if ! [[ "$IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || ! [[ "$EPOCH" =~ ^[0-9]+$ ]]; then
  echo "refused: MANIFEST names no usable image-id or source-date-epoch" >&2
  exit 1
fi

"$DOCKER" load --quiet --input "${BUNDLE}/toolchain/image.tar" >/dev/null
loaded="$("$DOCKER" image inspect --format '{{.Id}}' "$IMAGE_ID" 2>/dev/null)" || loaded=""
if [ "$loaded" != "$IMAGE_ID" ]; then
  echo "refused: toolchain/image.tar did not load the image the manifest names (${IMAGE_ID})" >&2
  exit 1
fi

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
chmod 0777 "$OUT"

# The rebuild's own exit status is recorded, not acted on: a rebuild that
# fails produces no deliverables, and compare reports each as not reproduced.
status=0
"$DOCKER" run --rm \
  --network none \
  --volume "${BUNDLE}:/bundle:ro" \
  --volume "${OUT}:/rebuilt" \
  --env "SOURCE_DATE_EPOCH=${EPOCH}" \
  --env "BUNDLE=/bundle" \
  --env "REBUILD_OUT=/rebuilt" \
  --entrypoint /bundle/rebuild \
  "$IMAGE_ID" || status=$?
if [ "$status" -ne 0 ]; then
  echo "the rebuild exited ${status}; the verdict records what it produced" >&2
fi

"$PYTHON" "${HERE}/bundle.py" compare --bundle "$BUNDLE" --rebuilt "$OUT" --out "$VERDICT"
