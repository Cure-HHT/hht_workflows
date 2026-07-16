#!/usr/bin/env python3
"""Extract the Firebase Test Lab history/execution IDs for a completed run.

run-android-test-lab.sh / run-ios-test-lab.sh do not write the Test Lab
history/execution IDs into execution-summary.json, but gcloud prints a
Firebase console URL of the form:

  https://console.firebase.google.com/project/<project>/testlab/histories/<history_id>/matrices/<execution_id>

to gcloud-output.log while the matrix runs. This script scans one or more
evidence directories for that log, extracts the first history/execution pair
found, and writes it out as JSON so downstream CI steps (e.g. the dashboard
publisher job) do not need to re-parse logs themselves.
"""
import argparse
import json
import re
import sys
from pathlib import Path

CONSOLE_URL_RE = re.compile(
    r"testlab/histories/(?P<history_id>[^/\s]+)/matrices/(?P<execution_id>[^/\s?#]+)"
)


def find_ids(evidence_dirs):
    # Search recursively: the evidence artifact roots at the platform dir
    # (e.g. android/), so after download the log sits one level deeper
    # (evidence/android/evidence/gcloud-output.log), and future layout
    # changes shouldn't silently break ID recovery.
    for evidence_dir in evidence_dirs:
        base = Path(evidence_dir)
        if not base.is_dir():
            continue
        for log_path in sorted(base.rglob("gcloud-output.log")):
            text = log_path.read_text(errors="replace")
            match = CONSOLE_URL_RE.search(text)
            if match:
                return match.group("history_id"), match.group("execution_id"), str(log_path)
    return None, None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir",
        action="append",
        required=True,
        help="Directory containing a gcloud-output.log (repeatable; first match wins).",
    )
    parser.add_argument("--output", required=True, help="Path to write the resulting JSON.")
    args = parser.parse_args()

    history_id, execution_id, source = find_ids(args.evidence_dir)

    if not history_id or not execution_id:
        print(
            "::error::Could not find a Firebase console history/execution URL in any "
            f"gcloud-output.log under {args.evidence_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Found historyId={history_id} executionId={execution_id} (source: {source})")
    Path(args.output).write_text(
        json.dumps({"historyId": history_id, "executionId": execution_id}, indent=2)
    )


if __name__ == "__main__":
    main()
