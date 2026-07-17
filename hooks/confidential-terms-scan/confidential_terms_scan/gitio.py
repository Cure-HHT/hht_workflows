"""Git plumbing for the confidential-terms scan.

Only added content and added/renamed paths are scanned
(HHT-OPS-confidential-keywords-scrubbing/D: "added content lines",
"added/renamed paths").
"""
import re
import subprocess

ZERO_SHA = "0" * 40
# Hash of git's canonical empty tree: diffing against it sees every path
# as added, which is the correct degraded mode when no base is resolvable.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_HUNK_RE = re.compile(r"@@ -\S+ \+(\d+)")


class GitError(Exception):
    pass


def run_git(args, cwd=None):
    # Config-proof diff headers: core.quotePath=false prevents octal escaping of
    # non-ASCII paths, and diff.mnemonicPrefix=false ensures consistent "+++ b/"
    # format instead of mnemonic prefixes. This module parses diff headers that
    # depend on this exact format.
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", "-c", "diff.mnemonicPrefix=false"]
        + list(args), capture_output=True, text=True, cwd=cwd
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip())
    return proc.stdout


def resolve_from_ref(from_ref, fallback_base):
    """A usable base ref: the given ref, else merge-base with
    fallback_base, else the empty tree (scan everything)."""
    if from_ref and from_ref != ZERO_SHA:
        return from_ref
    try:
        return run_git(["merge-base", fallback_base, "HEAD"]).strip()
    except GitError:
        return EMPTY_TREE


def added_lines(from_ref, to_ref):
    """Yield (path, new_lineno, text) for every added line in the range."""
    out = run_git(
        [
            "diff", "--no-color", "--unified=0", "--diff-filter=AMR",
            "--find-renames", "%s..%s" % (from_ref, to_ref),
        ]
    )
    path = None
    lineno = 0
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            path = line[len("+++ b/"):]
        elif line.startswith("@@"):
            match = _HUNK_RE.match(line)
            if not match:
                raise GitError("malformed hunk header in git diff output")
            lineno = int(match.group(1))
        elif line.startswith("+") and not line.startswith("+++") and path:
            # +++ /dev/null cannot appear here: --diff-filter=AMR excludes deletions.
            yield (path, lineno, line[1:])
            lineno += 1


def added_or_renamed_paths(from_ref, to_ref):
    """New paths introduced in the range: added files and rename targets."""
    out = run_git(
        [
            "diff", "--name-status", "-z", "--diff-filter=AR",
            "--find-renames", "%s..%s" % (from_ref, to_ref),
        ]
    )
    fields = out.split("\0")
    paths = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status.startswith("R"):
            paths.append(fields[i + 2])
            i += 3
        else:
            paths.append(fields[i + 1])
            i += 2
    return paths
