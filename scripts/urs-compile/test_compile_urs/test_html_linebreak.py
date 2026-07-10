"""Tests for pandoc-filters/html-linebreak.lua via the pandoc CLI."""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

FILTER = Path(__file__).parents[1] / "pandoc-filters" / "html-linebreak.lua"

pandoc_missing = shutil.which("pandoc") is None


def _docx_xml(md: str, tmp_path: Path) -> str:
    src = tmp_path / "t.md"
    out = tmp_path / "t.docx"
    src.write_text(md)
    subprocess.run(
        ["pandoc", str(src), "-f", "gfm", "-o", str(out), f"--lua-filter={FILTER}"],
        check=True,
    )
    return zipfile.ZipFile(out).read("word/document.xml").decode()


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_br_in_cell_becomes_real_line_break(tmp_path):
    # Two <br> in a merged "id then name" cell -> two real docx line breaks.
    xml = _docx_xml(
        "| entry_type | scope |\n"
        "|---|---|\n"
        "| `foo_bar`<br><br>(Foo Bar) | portal |\n",
        tmp_path,
    )
    # pandoc emits a hard break as <w:br /> (space before the slash).
    assert xml.count("<w:br />") == 2
    assert "Foo Bar" in xml


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_without_filter_br_is_dropped(tmp_path):
    # Guard the regression: the plain docx writer drops raw <br>.
    src = tmp_path / "t.md"
    out = tmp_path / "t.docx"
    src.write_text(
        "| entry_type | scope |\n"
        "|---|---|\n"
        "| `foo_bar`<br><br>(Foo Bar) | portal |\n"
    )
    subprocess.run(["pandoc", str(src), "-f", "gfm", "-o", str(out)], check=True)
    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    assert "<w:br />" not in xml


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
@pytest.mark.parametrize("br", ["<br>", "<br/>", "<br />", "<BR>"])
def test_br_spelling_variants(tmp_path, br):
    xml = _docx_xml(
        f"| a | b |\n|---|---|\n| x{br}y | z |\n",
        tmp_path,
    )
    assert xml.count("<w:br />") == 1
