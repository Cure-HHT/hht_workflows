"""Tests for pandoc-filters/catalog-tables.lua via the pandoc CLI."""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

FILTERS = Path(__file__).parents[1] / "pandoc-filters"
LINEBREAK = FILTERS / "html-linebreak.lua"
CATALOG = FILTERS / "catalog-tables.lua"

pandoc_missing = shutil.which("pandoc") is None

# A catalog table: merged "display name / entry_type" column + kinds. The
# registry variant leads with an aggregate column, exercising the by-header
# (not by-position) column detection.
REGISTRY_MD = (
    "| aggregate | Entry Display Name<br>`entry_type` | scope | kinds |\n"
    "|---|---|---|---|\n"
    # kinds are plain text in the generated catalog (comma-joined), not code
    # spans — a code run's VerbatimChar would otherwise win over the kind style.
    "| portal_user | User Created<br>`user_created` | portal | user_created |\n"
)
NON_CATALOG_MD = (
    "| Category | Action |\n"
    "|---|---|\n"
    "| Foo | Bar |\n"
)


def _docx_xml(md: str, tmp_path: Path) -> str:
    src = tmp_path / "t.md"
    out = tmp_path / "t.docx"
    src.write_text(md)
    subprocess.run(
        [
            "pandoc", str(src), "-t", "docx", "-o", str(out),
            f"--lua-filter={LINEBREAK}",
            f"--lua-filter={CATALOG}",
        ],
        check=True,
    )
    return zipfile.ZipFile(out).read("word/document.xml").decode()


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_catalog_cells_get_styled(tmp_path):
    xml = _docx_xml(REGISTRY_MD, tmp_path)
    # entry_type id run -> grey italic monospace character style
    assert 'w:val="CatalogEntryType"' in xml
    # entry cell paragraph -> keep-together style
    assert 'w:val="CatalogEntry"' in xml
    # kinds values -> monospace character style
    assert 'w:val="CatalogKind"' in xml


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_non_catalog_table_untouched(tmp_path):
    xml = _docx_xml(NON_CATALOG_MD, tmp_path)
    assert "Catalog" not in xml


@pytest.mark.skipif(pandoc_missing, reason="pandoc not on PATH")
def test_pdf_target_is_pass_through(tmp_path):
    # The filter is docx-only; a latex render must not carry the styles.
    src = tmp_path / "t.md"
    out = tmp_path / "t.tex"
    src.write_text(REGISTRY_MD)
    subprocess.run(
        [
            "pandoc", str(src), "-t", "latex", "-o", str(out),
            f"--lua-filter={LINEBREAK}",
            f"--lua-filter={CATALOG}",
        ],
        check=True,
    )
    assert "Catalog" not in out.read_text()
