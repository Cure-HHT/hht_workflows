"""Merge release-notes fragments into the appropriate sections of
RELEASE_NOTES.md. Routing-by-version logic lives here; the dedupe-append
of individual bullets lives in fragments.append_bullets so it's shared
with the publish action's slicer."""
from __future__ import annotations

from dataclasses import replace

from release_notes_update.fragments import Fragment, append_bullets
from release_notes_update.notes import Section, ensure_section


def consolidate_fragments(
    sections: list[Section],
    fragments: list[Fragment],
    *,
    today: str,
) -> list[Section]:
    """Append each fragment's bullets to the section matching its version.
    Creates the section if it doesn't yet exist. Dedupes bullets via
    append_bullets so behavior matches the publish-action slicer."""
    result = list(sections)
    for frag in fragments:
        result = ensure_section(result, version=frag.version, date=today)
        for i, s in enumerate(result):
            if s.version != frag.version:
                continue
            merged = append_bullets(s.entries, frag.bullets)
            if merged != s.entries:
                result[i] = replace(s, entries=merged)
            break
    return result
