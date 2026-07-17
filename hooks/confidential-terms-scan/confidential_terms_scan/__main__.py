"""confidential-terms-scan CLI.

Implements: HHT-OPS-confidential-keywords-scrubbing/C,D

Fetches CONFIDENTIAL_PROHIBIT_LIST (env var, else the consumer's scan-*
Doppler project via the developer's doppler CLI auth), scans the four
surfaces, and reports counts + locations only. Matched text, matching
path segments, and metadata text are never printed.

Exit codes: 0 pass / empty list / tolerated fetch failure, 1 findings,
2 configuration or fetch error.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import gitio
from .engine import (
    build_pattern,
    is_allowed,
    load_allow_globs,
    parse_prohibit_list,
    scan_content_lines,
    scan_metadata,
    scan_paths,
)

PROG = "confidential-terms-scan"


def parse_args(argv):
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--from-ref", default=None)
    parser.add_argument("--to-ref", default=None)
    parser.add_argument("--fallback-base", default="origin/main")
    parser.add_argument("--doppler-project", default=None)
    parser.add_argument("--doppler-config", default="prod")
    parser.add_argument("--on-fetch-error", choices=["fail", "warn"], default="fail")
    parser.add_argument("--allow-file", default=".confidential-terms-allow")
    return parser.parse_args(argv)


def fetch_from_doppler(project, config):
    """Read the list via the doppler CLI into memory. None on failure."""
    try:
        proc = subprocess.run(
            [
                "doppler", "secrets", "get", "CONFIDENTIAL_PROHIBIT_LIST",
                "--project", project, "--config", config, "--plain",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.rstrip("\r\n")


def main(argv=None):
    args = parse_args(argv)

    raw = os.environ.get("CONFIDENTIAL_PROHIBIT_LIST")
    if raw is None:
        if not args.doppler_project:
            print(
                "%s: CONFIDENTIAL_PROHIBIT_LIST is not set and no "
                "--doppler-project was given" % PROG,
                file=sys.stderr,
            )
            return 2
        raw = fetch_from_doppler(args.doppler_project, args.doppler_config)
        if raw is None:
            msg = "%s: could not fetch the prohibit list from Doppler project %s" % (
                PROG, args.doppler_project,
            )
            if args.on_fetch_error == "warn":
                print(
                    msg + " (tolerated: PR CI runs this scan as the "
                    "authoritative gate)",
                    file=sys.stderr,
                )
                return 0
            print(msg, file=sys.stderr)
            return 2

    pattern = build_pattern(parse_prohibit_list(raw))
    if pattern is None:
        print("%s: prohibit list is empty; nothing to scan" % PROG)
        return 0

    allow_path = Path(args.allow_file)
    allow = load_allow_globs(allow_path.read_text()) if allow_path.exists() else []

    from_ref = gitio.resolve_from_ref(
        args.from_ref or os.environ.get("PRE_COMMIT_FROM_REF"), args.fallback_base
    )
    to_ref = args.to_ref or os.environ.get("PRE_COMMIT_TO_REF") or "HEAD"

    findings = []
    findings += scan_content_lines(
        pattern,
        (
            (path, lineno, text)
            for path, lineno, text in gitio.added_lines(from_ref, to_ref)
            if not is_allowed(path, allow)
        ),
    )
    findings += scan_paths(
        pattern,
        [
            path
            for path in gitio.added_or_renamed_paths(from_ref, to_ref)
            if not is_allowed(path, allow)
        ],
    )
    findings += scan_metadata(
        pattern,
        {
            "branch-name": os.environ.get("BRANCH_NAME")
            or os.environ.get("PRE_COMMIT_REMOTE_BRANCH", ""),
            "pr-title": os.environ.get("PR_TITLE", ""),
            "pr-body": os.environ.get("PR_BODY", ""),
        },
    )

    if not findings:
        print("%s: PASS (no prohibited terms in the scanned range)" % PROG)
        return 0

    print("%s: FAIL - %d finding(s):" % (PROG, len(findings)), file=sys.stderr)
    for surface, location in findings:
        print("  %-12s %s" % (surface, location), file=sys.stderr)
    print(
        "Matched text is never printed; *** marks a matching path segment.\n"
        "Triage: ask 'should this reference exist in this repo at all?', "
        "not 'is this string secret?' - see hooks/confidential-terms-scan/"
        "README.md in Cure-HHT/hht_workflows.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
