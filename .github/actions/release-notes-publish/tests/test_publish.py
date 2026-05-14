"""Tests for release-notes-publish slice logic."""
from pathlib import Path
from textwrap import dedent

import pytest

from publish import slice_release_notes


def test_slice_top_section_only(tmp_path):
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text(dedent("""\
        # Release Notes

        ## v1.2.3+5 — 2026-05-13

        <!-- summary -->
        Top summary
        <!-- /summary -->

        <!-- entries -->
        - [CUR-1] First
        - [CUR-2] Second
        <!-- /entries -->

        ## v1.2.2+8 — 2026-05-01

        <!-- summary -->
        <!-- /summary -->

        <!-- entries -->
        - [CUR-0] Older
        <!-- /entries -->
    """))
    result = slice_release_notes(notes, fragments_dir=tmp_path / "no-such-dir")
    assert result["version"] == "v1.2.3+5"
    assert result["date"] == "2026-05-13"
    assert result["summary_block"] == "Top summary"
    assert result["entries_block"] == "- [CUR-1] First\n- [CUR-2] Second"


def test_slice_includes_pending_matching_version_fragments(tmp_path):
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text(dedent("""\
        # Release Notes

        ## v1.2.3+5 — 2026-05-13

        <!-- summary -->
        <!-- /summary -->

        <!-- entries -->
        - [CUR-1] First
        <!-- /entries -->
    """))
    frag_dir = tmp_path / ".release-notes"
    frag_dir.mkdir()
    (frag_dir / "feat-x.md").write_text(dedent("""\
        <!-- release-notes-fragment v1 -->
        <!-- version: v1.2.3+5 -->

        - [CUR-9] Last-minute straggler
    """))
    result = slice_release_notes(notes, fragments_dir=frag_dir)
    assert "- [CUR-9] Last-minute straggler" in result["entries_block"]


def test_slice_ignores_pending_other_version_fragments(tmp_path):
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text(dedent("""\
        # Release Notes

        ## v1.2.3+5 — 2026-05-13

        <!-- summary -->
        <!-- /summary -->

        <!-- entries -->
        - [CUR-1] First
        <!-- /entries -->
    """))
    frag_dir = tmp_path / ".release-notes"
    frag_dir.mkdir()
    (frag_dir / "feat-y.md").write_text(dedent("""\
        <!-- release-notes-fragment v1 -->
        <!-- version: v0.9.0+1 -->

        - [CUR-7] Orphan from older version
    """))
    result = slice_release_notes(notes, fragments_dir=frag_dir)
    assert "[CUR-7]" not in result["entries_block"]


def test_slice_raises_on_empty_notes(tmp_path):
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("# Release Notes\n")
    with pytest.raises(SystemExit):
        slice_release_notes(notes, fragments_dir=tmp_path / "no-such-dir")
