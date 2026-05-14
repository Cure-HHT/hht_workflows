"""Tests for consolidate module."""
from release_notes_update.consolidate import consolidate_fragments
from release_notes_update.fragments import Fragment
from release_notes_update.notes import Section


def test_consolidate_appends_to_matching_section():
    sections = [
        Section(version="v1.0.0+1", date="2026-05-01", entries=("- [CUR-1] existing",)),
    ]
    frags = [Fragment(version="v1.0.0+1", bullets=("[CUR-2] new entry",))]
    result = consolidate_fragments(sections, frags, today="2026-05-13")
    assert result[0].version == "v1.0.0+1"
    assert result[0].entries == (
        "- [CUR-1] existing",
        "- [CUR-2] new entry",
    )


def test_consolidate_creates_section_when_version_new():
    sections = [Section(version="v1.0.0+1", date="2026-05-01")]
    frags = [Fragment(version="v1.1.0+1", bullets=("[CUR-9] bump",))]
    result = consolidate_fragments(sections, frags, today="2026-05-13")
    assert [s.version for s in result] == ["v1.1.0+1", "v1.0.0+1"]
    assert result[0].entries == ("- [CUR-9] bump",)
    assert result[0].date == "2026-05-13"


def test_consolidate_skips_entries_already_in_section():
    """If a bullet is already in the section, don't add it again."""
    sections = [
        Section(version="v1.0.0+1", date="2026-05-01", entries=("- [CUR-1] foo",)),
    ]
    frags = [Fragment(version="v1.0.0+1", bullets=("[CUR-1] foo", "[CUR-2] bar"))]
    result = consolidate_fragments(sections, frags, today="2026-05-13")
    assert result[0].entries == ("- [CUR-1] foo", "- [CUR-2] bar")


def test_consolidate_multiple_fragments_same_version():
    sections = [Section(version="v1.0.0+1", date="2026-05-01")]
    frags = [
        Fragment(version="v1.0.0+1", bullets=("[CUR-1] a",)),
        Fragment(version="v1.0.0+1", bullets=("[CUR-2] b",)),
    ]
    result = consolidate_fragments(sections, frags, today="2026-05-13")
    assert result[0].entries == ("- [CUR-1] a", "- [CUR-2] b")


def test_consolidate_preserves_unchanged_sections():
    sections = [
        Section(version="v1.0.0+1", date="2026-05-01", entries=("- [CUR-1] a",)),
        Section(version="v0.9.0+1", date="2026-04-01", entries=("- [CUR-0] old",)),
    ]
    frags = []
    result = consolidate_fragments(sections, frags, today="2026-05-13")
    assert result == sections
