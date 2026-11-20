"""normalise.py: a deliverable's bytes follow from its content alone.

Each case builds two files that say the same thing and differ only where a
compile run leaves its mark -- the PDF identifier, the archive timestamps, the
Office clock properties -- and asserts that normalising makes them equal. The
negative controls assert that a difference in content survives, because a
normaliser that made everything equal would pass every positive case.
"""

from __future__ import annotations

import io
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "normalise.py"
sys.path.insert(0, str(HERE.parent))

import normalise as nm  # noqa: E402

EPOCH = 1788998400  # 2026-09-10T00:00:00Z


def _pdf(body: bytes, ident: bytes) -> bytes:
    """A PDF-shaped byte string: a body, a cross-reference offset, and a trailer
    carrying /ID the way XeTeX writes it."""
    return (
        b"%PDF-1.5\n" + body + b"\nxref\n0 1\n0000000000 65535 f \n"
        b"trailer\n<</Size 1/Root 1 0 R/ID[<" + ident + b"><" + ident + b">]>>\n"
        b"startxref\n9\n%%EOF\n"
    )


def _docx(core_time: str, parts: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=time.gmtime()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
        core = (
            '<cp:coreProperties xmlns:dcterms="http://purl.org/dc/terms/">'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{core_time}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{core_time}</dcterms:modified>'
            "</cp:coreProperties>"
        ).encode()
        z.writestr("docProps/core.xml", core)
    return buf.getvalue()


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


# --- PDF ---------------------------------------------------------------------


def test_two_pdfs_differing_only_in_their_identifier_become_identical(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(_pdf(b"same content", b"6EBCE1990B1B20F9DCB4CFF4FA85E8E4"))
    b.write_bytes(_pdf(b"same content", b"482CB324B2F0E0790E9B9222A3BB513F"))
    assert a.read_bytes() != b.read_bytes()
    assert _run("--epoch", str(EPOCH), str(a), str(b)).returncode == 0
    assert a.read_bytes() == b.read_bytes()


def test_the_pdf_keeps_its_length_so_cross_reference_offsets_stay_valid():
    before = _pdf(b"x" * 100, b"0123456789ABCDEF0123456789ABCDEF")
    after = nm.normalise_pdf_bytes(before)
    assert len(after) == len(before)
    assert after != before


def test_normalising_a_pdf_twice_is_a_no_op():
    once = nm.normalise_pdf_bytes(_pdf(b"body", b"AB" * 16))
    assert nm.normalise_pdf_bytes(once) == once


def test_the_identifier_is_a_function_of_the_content():
    """Negative control: two documents that say different things keep
    different identifiers, so the identifier still distinguishes them."""
    a = nm.normalise_pdf_bytes(_pdf(b"content one", b"AB" * 16))
    b = nm.normalise_pdf_bytes(_pdf(b"content two", b"AB" * 16))
    assert a.split(b"/ID")[1] != b.split(b"/ID")[1]


def test_a_cross_reference_stream_identifier_with_spaces_is_normalised():
    data = b"<</Type/XRef/ID [ <AAAA> <BBBB> ]>>"
    out = nm.normalise_pdf_bytes(data)
    assert b"AAAA" not in out and b"BBBB" not in out
    assert len(out) == len(data)


# --- ZIP (DOCX/XLSX) ---------------------------------------------------------


def test_two_archives_differing_only_in_timestamps_and_order_become_identical(tmp_path):
    parts = [("[Content_Types].xml", b"<Types/>"), ("word/document.xml", b"<w:document/>")]
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    a.write_bytes(_docx("2026-11-20T10:00:00Z", parts))
    time.sleep(2)  # ZIP time resolution is two seconds
    b.write_bytes(_docx("2026-11-20T10:00:02Z", list(reversed(parts))))
    assert a.read_bytes() != b.read_bytes()
    assert _run("--epoch", str(EPOCH), str(a), str(b)).returncode == 0
    assert a.read_bytes() == b.read_bytes()


def test_entries_carry_the_epoch_and_the_content_types_part_comes_first(tmp_path):
    f = tmp_path / "w.xlsx"
    f.write_bytes(_docx("2030-01-01T00:00:00Z", [("xl/workbook.xml", b"<wb/>"), ("[Content_Types].xml", b"<T/>")]))
    nm.normalise(f, EPOCH)
    with zipfile.ZipFile(f) as z:
        infos = z.infolist()
        assert infos[0].filename == "[Content_Types].xml"
        assert {i.date_time for i in infos} == {(2026, 9, 10, 0, 0, 0)}
        core = z.read("docProps/core.xml").decode()
    assert core.count("2026-09-10T00:00:00Z") == 2
    assert "2030" not in core


def test_archive_content_survives_normalisation(tmp_path):
    f = tmp_path / "w.docx"
    f.write_bytes(_docx("2026-01-01T00:00:00Z", [("word/document.xml", b"<w:document>hello</w:document>")]))
    nm.normalise(f, EPOCH)
    with zipfile.ZipFile(f) as z:
        assert z.read("word/document.xml") == b"<w:document>hello</w:document>"


def test_archives_that_say_different_things_stay_different(tmp_path):
    """Negative control for the archive case."""
    a, b = tmp_path / "a.docx", tmp_path / "b.docx"
    a.write_bytes(_docx("2026-01-01T00:00:00Z", [("word/document.xml", b"one")]))
    b.write_bytes(_docx("2026-01-01T00:00:00Z", [("word/document.xml", b"two")]))
    nm.normalise(a, EPOCH)
    nm.normalise(b, EPOCH)
    assert a.read_bytes() != b.read_bytes()


def test_normalising_an_archive_twice_is_a_no_op(tmp_path):
    f = tmp_path / "w.docx"
    f.write_bytes(_docx("2026-01-01T00:00:00Z", [("word/document.xml", b"x")]))
    nm.normalise(f, EPOCH)
    once = f.read_bytes()
    nm.normalise(f, EPOCH)
    assert f.read_bytes() == once


def test_an_epoch_before_1980_is_clamped_to_the_zip_floor(tmp_path):
    f = tmp_path / "w.zip"
    f.write_bytes(_docx("2026-01-01T00:00:00Z", [("a.txt", b"x")]))
    nm.normalise(f, 0)
    with zipfile.ZipFile(f) as z:
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}


# --- refusals ----------------------------------------------------------------


def test_an_unknown_extension_is_refused_not_passed_over(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("x")
    r = _run("--epoch", str(EPOCH), str(f))
    assert r.returncode == 1
    assert "no normalisation is defined" in r.stderr


def test_a_missing_file_is_refused(tmp_path):
    r = _run("--epoch", str(EPOCH), str(tmp_path / "absent.pdf"))
    assert r.returncode == 1


def test_a_negative_epoch_is_refused(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(_pdf(b"x", b"AB" * 16))
    r = _run("--epoch", "-1", str(f))
    assert r.returncode != 0


@pytest.mark.parametrize("bad", [b"not a zip"])
def test_a_corrupt_archive_is_refused(tmp_path, bad):
    f = tmp_path / "a.docx"
    f.write_bytes(bad)
    r = _run("--epoch", str(EPOCH), str(f))
    assert r.returncode == 1
