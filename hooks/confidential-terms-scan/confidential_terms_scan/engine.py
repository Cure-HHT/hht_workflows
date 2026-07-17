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


def build_pattern(terms):
    """Word-boundary, case-insensitive alternation. None when no terms."""
    if not terms:
        return None
    # For terms with hyphens, match as prefix (allow word chars after).
    # For other terms, use word boundaries on both sides.
    sorted_terms = sorted(terms)
    patterns = []
    for term in sorted_terms:
        escaped = re.escape(term)
        if "-" in term:
            patterns.append(r"\b%s\w*" % escaped)
        else:
            patterns.append(r"\b%s\b" % escaped)
    alternation = "|".join(patterns)
    return re.compile("(?:%s)" % alternation, re.IGNORECASE)


def scan_content_lines(pattern, lines):
    """lines: iterable of (path, lineno, text). Location is path:lineno."""
    return [
        ("content", "%s:%d" % (path, lineno))
        for path, lineno, text in lines
        if pattern.search(text)
    ]


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
