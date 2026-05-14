"""Generate, parse, and discover release-notes fragment files, and merge
their bullets into existing entry lists.

Shared between the pre-commit hook (which discovers fragments via git on
origin/main, then retires them by consolidation) and the publish action
(which discovers fragments on the filesystem, then compiles them into the
sliced section). Both use the same parsing pipeline and dedupe-append
helper so the discovery/merge logic is defined once."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, TypeVar

_HEADER = "<!-- release-notes-fragment v1 -->"
_VERSION_RE = re.compile(r"^<!-- version: (.+) -->$")
_BULLET_RE = re.compile(r"^- (\[CUR-\d+\].*)$")
_CUR_PREFIX_RE = re.compile(r"^\[CUR-\d+\]")

_ID = TypeVar("_ID")


@dataclass(frozen=True)
class Fragment:
    version: str
    bullets: tuple[str, ...] = ()

    def __init__(self, version: str, bullets):
        # Normalize to tuple for hashability/equality.
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "bullets", tuple(bullets))


def fragment_from_commits(commit_subjects, *, version: str) -> Fragment:
    """Build a fragment from a list of commit subject lines, keeping only
    those starting with the [CUR-XXX] prefix."""
    bullets = [s for s in commit_subjects if _CUR_PREFIX_RE.match(s)]
    return Fragment(version=version, bullets=bullets)


def render_fragment(frag: Fragment) -> str:
    """Render a Fragment to its canonical file format string."""
    lines = [_HEADER, f"<!-- version: {frag.version} -->", ""]
    lines.extend(f"- {b}" for b in frag.bullets)
    return "\n".join(lines) + "\n"


def parse_fragment(text: str) -> Fragment:
    """Parse a fragment file string into a Fragment. Raises ValueError if
    the content does not match the expected v1 format."""
    lines = text.splitlines()
    if not lines or lines[0] != _HEADER:
        raise ValueError("unknown fragment format: missing v1 header")
    version = None
    bullets = []
    for line in lines[1:]:
        if not line.strip():
            continue
        m = _VERSION_RE.match(line)
        if m:
            version = m.group(1)
            continue
        b = _BULLET_RE.match(line)
        if b:
            bullets.append(b.group(1))
            continue
        # Ignore unknown lines (forward-compat).
    if version is None:
        raise ValueError("unknown fragment format: missing version metadata")
    return Fragment(version=version, bullets=bullets)


def parse_fragments(
    source: Iterable[tuple[_ID, str]],
) -> Iterator[tuple[_ID, Fragment]]:
    """Parse a stream of (identifier, content) pairs into (identifier, Fragment)
    pairs. Malformed entries are skipped with a warning to stderr. The
    identifier is opaque to this function — pass whatever lets the caller
    refer back to the source (a filesystem path, a git path string, etc.)."""
    for ident, content in source:
        try:
            yield (ident, parse_fragment(content))
        except ValueError as e:
            print(
                f"release-notes: skipping malformed fragment {ident}: {e}",
                file=sys.stderr,
            )


def read_fragments_dir(path: Path) -> Iterator[tuple[Path, str]]:
    """Yield (path, content) for every .md file directly in `path`, sorted
    by filename. Returns an empty iterator if the directory does not exist.
    Subdirectories are ignored (fragments live flat in `.release-notes/`)."""
    if not path.exists() or not path.is_dir():
        return
    for fp in sorted(path.iterdir()):
        if fp.is_file() and fp.suffix == ".md":
            yield (fp, fp.read_text())


def append_bullets(
    entries: tuple[str, ...], bullets: Iterable[str]
) -> tuple[str, ...]:
    """Return `entries` with each bullet from `bullets` appended as a
    `- <bullet>` line, skipping any line already present (preserves order
    of first occurrence; dedupes both against existing entries and within
    the new batch)."""
    seen = set(entries)
    out = list(entries)
    for b in bullets:
        line = f"- {b}"
        if line in seen:
            continue
        out.append(line)
        seen.add(line)
    return tuple(out)
