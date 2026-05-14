"""Parse and render RELEASE_NOTES.md."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

_HEADER = "# Release Notes"
_SECTION_RE = re.compile(r"^## (v\S+) — (\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class Section:
    version: str
    date: str
    summary: str = ""
    entries: tuple[str, ...] = ()


def parse_notes(text: str) -> list[Section]:
    """Parse RELEASE_NOTES.md content into an ordered list of Sections (top-first)."""
    lines = text.splitlines()
    sections: list[Section] = []
    i = 0
    while i < len(lines):
        m = _SECTION_RE.match(lines[i])
        if not m:
            i += 1
            continue
        version, date = m.group(1), m.group(2)
        i += 1
        summary, entries = "", []
        # Scan forward until next ## heading or EOF.
        while i < len(lines) and not _SECTION_RE.match(lines[i]):
            if lines[i] == "<!-- summary -->":
                buf = []
                i += 1
                while i < len(lines) and lines[i] != "<!-- /summary -->":
                    buf.append(lines[i])
                    i += 1
                summary = "\n".join(buf).strip()
                if i < len(lines) and lines[i] == "<!-- /summary -->":
                    i += 1
            elif lines[i] == "<!-- entries -->":
                i += 1
                while i < len(lines) and lines[i] != "<!-- /entries -->":
                    if lines[i].strip():
                        entries.append(lines[i])
                    i += 1
                if i < len(lines) and lines[i] == "<!-- /entries -->":
                    i += 1
            else:
                i += 1
        sections.append(Section(version=version, date=date, summary=summary, entries=tuple(entries)))
    return sections


def render_notes(sections: list[Section]) -> str:
    """Render an ordered list of Sections back to RELEASE_NOTES.md text.
    The output is the inverse of parse_notes for any input the parser produced."""
    if not sections:
        return _HEADER + "\n"
    out = [_HEADER, ""]
    for s in sections:
        out.append(f"## {s.version} — {s.date}")
        out.append("")
        out.append("<!-- summary -->")
        if s.summary:
            out.append(s.summary)
        out.append("<!-- /summary -->")
        out.append("")
        out.append("<!-- entries -->")
        out.extend(s.entries)
        out.append("<!-- /entries -->")
        out.append("")
    return "\n".join(out)


def ensure_section(
    sections: list[Section], *, version: str, date: str
) -> list[Section]:
    """If a section for `version` exists, return sections unchanged (date is
    not overwritten — the original section's date wins). Otherwise prepend a
    new empty section at the top."""
    for s in sections:
        if s.version == version:
            return list(sections)
    return [Section(version=version, date=date)] + list(sections)
