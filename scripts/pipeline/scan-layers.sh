#!/usr/bin/env bash
# Scan every layer of an image for secrets, one layer at a time.
#
# Why per layer, and why decompressed:
#
# A value written to a file in an early step cannot be removed by a later one.
# Deleting it adds a whiteout to a later layer; the bytes stay readable to
# anyone who can read the earlier one. So scanning the image's final filesystem
# answers the wrong question -- it reports clean on an image that is leaking.
#
# And layer blobs are gzip. An "appears nowhere" grep over the blobs passes on a
# leaking image because the plaintext is not there to find. That is not a
# hypothetical: it was reproduced inside this mechanism before it shipped, and
# it is the same shape as CUR-1424, a gate that passed vacuously for months.
#
# Both image layouts are handled. The runner's daemon may write an OCI layout
# (blobs/sha256/*) or the legacy one (<hash>/layer.tar), and a script that knows
# only the layout on the author's machine finds nothing on the other.
#
# Findings are reported by count and location. The value is never echoed --
# printing a secret to a build log to prove it leaked is not an improvement.
#
# Usage: scan-layers.sh <image-ref> [--expect-findings]
#
# Exit status:
#   0  scanned, and the result was the expected one
#   1  the result was not the expected one (a leak, or a positive control that
#      failed to reproduce)
#   2  operational error -- could not scan. Never reported as clean.

set -euo pipefail

ref="${1:?usage: scan-layers.sh <image-ref> [--expect-findings]}"
expect_findings=false
if [ "${2:-}" = "--expect-findings" ]; then
    expect_findings=true
fi

if ! command -v gitleaks > /dev/null 2>&1; then
    echo "::error::gitleaks is not installed; refusing to report an unscanned image as clean" >&2
    exit 2
fi
if ! command -v docker > /dev/null 2>&1; then
    echo "::error::docker is not available; cannot export layers" >&2
    exit 2
fi

# The layer-scan config, not the repository's commit-time gate. See the file's
# own header for why it carries an allowlist and the gate does not.
config="$(cd "$(dirname "$0")" && pwd)/layer-scan.toml"
if [ ! -f "$config" ]; then
    echo "::error::layer-scan.toml is missing; refusing to scan with unknown rules" >&2
    exit 2
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "exporting $ref"
docker save "$ref" -o "$work/image.tar"
mkdir -p "$work/image"
tar -xf "$work/image.tar" -C "$work/image"

# Both layouts, in one list. Each `find` is guarded by the directory existing
# rather than by swallowing its failure: a find that errored and a find that
# matched nothing are different facts, and only one of them is fine.
layer_list="$work/layers.txt"
: > "$layer_list"
if [ -d "$work/image/blobs/sha256" ]; then
    find "$work/image/blobs/sha256" -type f >> "$layer_list"
fi
find "$work/image" -name 'layer.tar' -type f >> "$layer_list"
layers="$(sort -u "$layer_list")"

if [ -z "$layers" ]; then
    echo "::error::no layer blobs found in the export; the layout is not one this script knows" >&2
    exit 2
fi

total_findings=0
scanned=0
leaking_layers=0
partial_layers=0

while IFS= read -r blob; do
    [ -n "$blob" ] || continue

    dest="$work/extract/$(basename "$blob")"
    mkdir -p "$dest"

    # A blob is a tar, a gzipped tar, or a JSON config. Only the first two are
    # filesystem content; anything else is skipped rather than guessed at.
    #
    # A partial extraction REFUSES, and that is a deliberate change from saying
    # so and carrying on. The files that failed to extract are precisely the
    # ones never scanned, so gitleaks finding nothing in what did extract would
    # report the layer clean on evidence that excludes the unexamined part --
    # the same shape as the gate that passed vacuously for months under
    # CUR-1424. A scan that cannot see everything must not be allowed to say
    # everything is fine.
    #
    # If a benign entry type (device nodes, duplicate whiteouts) turns out to be
    # common, exclude exactly that entry with `--exclude` so extraction is whole
    # again. Do not relax this back into a note: the excluded thing is then
    # named and reviewable, which "extracted partially" never was.
    if tar -tzf "$blob" > /dev/null 2>&1; then
        if ! tar -xzf "$blob" -C "$dest" 2> "$work/tar.err"; then
            partial_layers=$((partial_layers + 1))
            echo "::error::$(basename "$blob") extracted partially, so part of this layer was never scanned" >&2
            if [ -s "$work/tar.err" ]; then
                sed 's/^/  tar: /' "$work/tar.err" >&2
            fi
        fi
    elif tar -tf "$blob" > /dev/null 2>&1; then
        if ! tar -xf "$blob" -C "$dest" 2> "$work/tar.err"; then
            partial_layers=$((partial_layers + 1))
            echo "::error::$(basename "$blob") extracted partially, so part of this layer was never scanned" >&2
            if [ -s "$work/tar.err" ]; then
                sed 's/^/  tar: /' "$work/tar.err" >&2
            fi
        fi
    else
        continue
    fi

    scanned=$((scanned + 1))
    report="$work/report-$(basename "$blob").json"

    if gitleaks dir "$dest" --no-banner --redact --config "$config" \
            --report-format json --report-path "$report" > /dev/null 2>&1; then
        continue
    fi

    # gitleaks exited non-zero. That means findings, or that it could not run.
    # Those need different answers, so read the report rather than assume.
    if [ ! -s "$report" ]; then
        echo "::error::gitleaks failed on layer $(basename "$blob") and wrote no report" >&2
        exit 2
    fi
    if ! count="$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$report")"; then
        echo "::error::gitleaks report for $(basename "$blob") is unreadable" >&2
        exit 2
    fi
    if [ "$count" -gt 0 ]; then
        leaking_layers=$((leaking_layers + 1))
        total_findings=$((total_findings + count))
        echo "layer $(basename "$blob"): $count finding(s)"
        python3 - "$report" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    findings = json.load(handle)

for item in findings:
    # Location and rule only. Never the value.
    print(f"  {item.get('File', '?')}:{item.get('StartLine', '?')} [{item.get('RuleID', '?')}]")
PY
    fi
done <<< "$layers"

echo "scanned $scanned layer(s) of $ref: $total_findings finding(s) in $leaking_layers layer(s)"

# Before any verdict about findings: if a layer did not extract whole, this run
# does not know what was in it. Refuse rather than report on a subset.
if [ "$partial_layers" -gt 0 ]; then
    echo "::error::$partial_layers layer(s) did not extract completely; this scan cannot speak for them" >&2
    exit 2
fi

if [ "$scanned" -eq 0 ]; then
    echo "::error::no layer carried filesystem content; nothing was actually scanned" >&2
    exit 2
fi

if [ "$expect_findings" = true ]; then
    if [ "$total_findings" -eq 0 ]; then
        echo "::error::positive control found nothing. The scan cannot fail, so its clean results mean nothing." >&2
        exit 1
    fi
    echo "positive control reproduced: the scan detects a secret hidden by a later layer"
    exit 0
fi

if [ "$total_findings" -gt 0 ]; then
    echo "::error::$total_findings secret finding(s) across $leaking_layers layer(s) of $ref" >&2
    exit 1
fi

echo "no findings"
