"""Tests for notes module."""
import pytest

from release_notes_update.notes import (
    Section,
    parse_notes,
    render_notes,
    ensure_section,
)


SAMPLE = """# Release Notes

## v1.2.3+5 — 2026-05-13

<!-- summary -->
<!-- /summary -->

<!-- entries -->
- [CUR-1] First entry
- [CUR-2] Second entry
<!-- /entries -->

## v1.2.2+8 — 2026-05-01

<!-- summary -->
<!-- /summary -->

<!-- entries -->
- [CUR-0] Older entry
<!-- /entries -->
"""


def test_parse_sections_preserves_order_top_first():
    notes = parse_notes(SAMPLE)
    assert [s.version for s in notes] == ["v1.2.3+5", "v1.2.2+8"]


def test_parse_section_entries_and_summary():
    notes = parse_notes(SAMPLE)
    top = notes[0]
    assert top.date == "2026-05-13"
    assert top.summary == ""
    assert top.entries == ("- [CUR-1] First entry", "- [CUR-2] Second entry")


def test_render_roundtrip():
    notes = parse_notes(SAMPLE)
    assert render_notes(notes) == SAMPLE


def test_ensure_section_creates_when_missing():
    notes = parse_notes(SAMPLE)
    updated = ensure_section(notes, version="v1.3.0+1", date="2026-06-01")
    assert [s.version for s in updated] == ["v1.3.0+1", "v1.2.3+5", "v1.2.2+8"]
    assert updated[0].entries == ()
    assert updated[0].date == "2026-06-01"


def test_ensure_section_noop_when_present():
    notes = parse_notes(SAMPLE)
    updated = ensure_section(notes, version="v1.2.3+5", date="2099-99-99")
    assert [s.version for s in updated] == ["v1.2.3+5", "v1.2.2+8"]
    assert updated[0].date == "2026-05-13"


def test_parse_empty_file_returns_empty_list():
    assert parse_notes("# Release Notes\n") == []


def test_render_empty_emits_header_only():
    assert render_notes([]) == "# Release Notes\n"
