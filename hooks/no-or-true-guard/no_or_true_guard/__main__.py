"""Fail the commit if a staged file contains the banned '|| true' / '|| :' pattern."""
import re
import sys

PATTERN = re.compile(r"\|\|\s*(?:true|:)(?:\W|$)")


def scan(paths):
    violations = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
                for lineno, line in enumerate(f, start=1):
                    if PATTERN.search(line):
                        violations.append((path, lineno, line.strip()))
        except OSError as exc:
            print(f"no-or-true-guard: warning: could not read {path}: {exc}", file=sys.stderr)
            violations.append((path, 0, "<unreadable — treated as a violation, fail-closed>"))
    return violations


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    violations = scan(argv)
    if not violations:
        return 0
    print(
        "no-or-true-guard: '|| true' / '|| :' is prohibited — use an explicit "
        "scoped conditional instead (see hooks/no-or-true-guard/README.md "
        "'Accepted replacement forms')."
    )
    for path, lineno, line in violations:
        print(f"  {path}:{lineno}: {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
