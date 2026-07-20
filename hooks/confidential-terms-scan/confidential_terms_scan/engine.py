"""Pure scan primitives for the confidential-terms guard.

Implements: HHT-OPS-confidential-keywords-scrubbing/C,D

The prohibit list is held in memory only. Nothing in this module may emit
matched text: findings are (surface, location) tuples where location is a
file:line, a masked path (matching segments replaced by MASK), or a
PR-metadata field name.
"""
import fnmatch
import re

MASK = "***"


def parse_prohibit_list(raw):
    """Comma-separated plain words -> non-empty stripped terms."""
    return [t.strip() for t in raw.split(",") if t.strip()]


# A term matches at a letter boundary: nothing letter-like immediately
# before it, or a lowercase-to-uppercase transition (camelCase embedding).
# There is no trailing constraint: identifier tails (for_callisto,
# callisto4, CallistoService, callistos) are exactly the mistakes the
# guard exists to catch, and the registry lint requires terms distinctive
# enough that substring tails cannot collide with ordinary words.
_LEAD = r"(?:(?<![A-Za-z])|(?<=[a-z])(?=[A-Z]))"


def build_pattern(terms):
    """Letter-boundary, case-insensitive alternation. None when no terms.

    Case-insensitivity is scoped to the terms via (?i:...) so the
    case-transition lookaround stays case-sensitive; a global IGNORECASE
    would make (?=[A-Z]) match lowercase and erase the boundary.
    """
    if not terms:
        return None
    alternation = "|".join(re.escape(t) for t in sorted(terms))
    return re.compile(_LEAD + r"(?i:%s)" % alternation)


def mask_path(path, pattern):
    """Replace each matching path segment with MASK. -> (masked, hit)."""
    hit = False
    out = []
    for segment in path.split("/"):
        if pattern.search(segment):
            hit = True
            out.append(MASK)
        else:
            out.append(segment)
    return "/".join(out), hit


def scan_content_lines(pattern, lines):
    """lines: iterable of (path, lineno, text). Location is masked-path:lineno."""
    return [
        ("content", "%s:%d" % (mask_path(path, pattern)[0], lineno))
        for path, lineno, text in lines
        if pattern.search(text)
    ]


def scan_paths(pattern, paths):
    """Findings for added/renamed paths: basename hits are 'filename',
    other segment hits are 'path-segment'. Locations are masked paths."""
    findings = []
    for path in paths:
        masked, hit = mask_path(path, pattern)
        if not hit:
            continue
        surface = "filename" if pattern.search(path.split("/")[-1]) else "path-segment"
        findings.append((surface, masked))
    return findings


def scan_metadata(pattern, fields):
    """fields: name -> text. Findings carry the field NAME only."""
    return [
        ("metadata", name)
        for name, text in sorted(fields.items())
        if text and pattern.search(text)
    ]


def load_allow_globs(text):
    """Path globs, one per line; blank lines and # comments ignored."""
    globs = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            globs.append(line)
    return globs


def is_allowed(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)
