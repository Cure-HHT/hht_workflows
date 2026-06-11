"""Tests for pandoc-filters/table-autofit-docx.lua via the pandoc CLI."""

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

FILTER = Path(__file__).parents[1] / "pandoc-filters" / "table-autofit-docx.lua"

pandoc_missing = shutil.which("pandoc") is None


def _grid_cols(md: str, tmp_path: Path) -> list[int]:
    src = tmp_path / "t.md"
    out = tmp_path / "t.docx"
    src.write_text(md)
    subprocess.run(
        ["pandoc", str(src), "-o", str(out), f"--lua-filter={FILTER}"],
        check=True,
    )
    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    return [int(m) for m in re.findall(r'<w:gridCol w:w="(\d+)"', xml)]


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_pipe_table_columns_sized_by_content(tmp_path):
    cols = _grid_cols(
        "| *Action* ID | *Action* | Study Coordinator | CRA | Administrator |\n"
        "| ----- | ----- | ----- | ----- | ----- |\n"
        "| ACT-QST-001 | Send *Questionnaire* | Y* | N | N |\n"
        "| ACT-QST-002 | Call back *Questionnaire* | Y* | N | N |\n",
        tmp_path,
    )
    assert len(cols) == 5
    id_col, action_col, sc_col, cra_col, admin_col = cols
    # CRA (Y/N values, 3-char header) is the narrowest column by far.
    assert cra_col == min(cols)
    assert action_col > id_col > cra_col
    # Floors: the ID column must hold "ACT-QST-001" (11 chars) on one
    # line — more than 12% of the total width.
    assert id_col / sum(cols) > 0.12


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_long_line_pipe_table_equal_widths_recomputed(tmp_path):
    # A pipe-table line longer than pandoc's --columns makes pandoc
    # assign widths from the separator dashes — all equal for the
    # uniform separators elspais emits. Those must be recomputed, not
    # treated as authored.
    cols = _grid_cols(
        "| Category | *Action* ID | *Action* |\n"
        "| :---- | :---- | :---- |\n"
        "| **Participant Management** | ACT-PAT-001 | Link *Participant* |\n"
        "|  | ACT-PAT-005 | Mark *Participant* as not participating in this study |\n",
        tmp_path,
    )
    assert len(cols) == 3
    assert len(set(cols)) > 1, "equal pandoc-derived widths were not recomputed"


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_authored_unequal_widths_kept(tmp_path):
    # Grid tables carry author-drawn column proportions; unequal widths
    # signal intent and must survive (1:3 here).
    cols = _grid_cols(
        "+------+------------------+\n"
        "| Ver  | Description      |\n"
        "+======+==================+\n"
        "| 1.0  | Initial draft    |\n"
        "+------+------------------+\n",
        tmp_path,
    )
    assert len(cols) == 2
    ratio = cols[1] / cols[0]
    assert 2.0 < ratio < 3.5, f"authored 1:~2.6 ratio not preserved: {cols}"


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_empty_column_absorbs_spare_width(tmp_path):
    # Signature-block shape: the empty Signature column must stay wide
    # (it is there to be written in), not collapse to nothing.
    cols = _grid_cols(
        "+----------------------+----------------------+\n"
        "| Approver             | Signature            |\n"
        "+======================+======================+\n"
        "| First Name Last Name |                      |\n"
        "+----------------------+----------------------+\n",
        tmp_path,
    )
    assert len(cols) == 2
    assert cols[1] / sum(cols) > 0.3, f"empty column collapsed: {cols}"
