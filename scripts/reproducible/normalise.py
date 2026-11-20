#!/usr/bin/env python3
"""Make a compiled deliverable's bytes a function of its content alone.

Two compiles of the same sources under the same SOURCE_DATE_EPOCH produce
documents that say the same thing in bytes that are not equal
(docs/urs-reproducibility-findings.md). Two things move, and neither is part of
what the document says:

  PDF   XeTeX writes a per-run document identifier into the trailer's /ID.
        It is not a timestamp, so SOURCE_DATE_EPOCH does not fix it.

  ZIP   (DOCX, XLSX) every archive entry carries the time it was written.
        pandoc honours SOURCE_DATE_EPOCH; python-docx and openpyxl, which
        rewrite the archive afterwards, stamp the wall clock instead, and
        openpyxl also writes the wall clock into the document's own
        created/modified properties (docProps/core.xml).

This rewrites each in place so the bytes follow from the content: the PDF's
identifier becomes a digest of the file with the identifier blanked, every
archive entry gets the epoch's timestamp, a fixed order and fixed attributes, and
the Office created/modified properties are set to the epoch.
Normalising twice is a no-op, which is what lets a rebuild compare bytes.

Usage:
  normalise.py --epoch SECONDS FILE...

The type is taken from the extension (.pdf; .docx, .xlsx, .zip). Any other
extension is refused rather than passed over: a file named for normalising that
was silently left alone is a byte comparison that fails later for no reason the
reader can see.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

#: The trailer (or cross-reference stream) identifier: two hex strings in an
#: array, `/ID [<hex><hex>]`, with optional whitespace between the tokens.
_PDF_ID = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\]")

#: The earliest time a ZIP entry can record (MS-DOS epoch).
_ZIP_FLOOR = (1980, 1, 1, 0, 0, 0)

ZIP_SUFFIXES = {".docx", ".xlsx", ".zip"}

#: The Office core-properties part, and the two clock values it carries.
_CORE_PART = "docProps/core.xml"
_CORE_TIMES = re.compile(rb"(<dcterms:(created|modified)\b[^>]*>)[^<]*(</dcterms:\2>)")


def normalise_pdf_bytes(data: bytes) -> bytes:
    """Replace every /ID pair with a digest of the file's other bytes.

    The replacement is the same length as what it replaces, so every byte
    offset in the cross-reference table stays correct. Both halves of the pair
    take the same value, as XeTeX itself writes them for a new document.
    """
    matches = list(_PDF_ID.finditer(data))
    if not matches:
        return data

    # Blank the identifiers, then hash: the digest must not depend on the value
    # being replaced, or normalising twice would give a different answer.
    blanked = bytearray(data)
    for m in matches:
        for group in (1, 2):
            start, end = m.span(group)
            blanked[start:end] = b"0" * (end - start)
    digest = hashlib.sha256(bytes(blanked)).hexdigest().upper().encode("ascii")

    out = bytearray(blanked)
    for m in matches:
        for group in (1, 2):
            start, end = m.span(group)
            width = end - start
            # Repeat the digest when an identifier is wider than one, so the
            # length is kept whatever width the writer chose.
            fill = (digest * (width // len(digest) + 1))[:width]
            out[start:end] = fill
    return bytes(out)


def _zip_time(epoch: int) -> tuple[int, int, int, int, int, int]:
    moment = datetime.fromtimestamp(epoch, tz=timezone.utc)
    stamp = (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second)
    # ZIP stores even seconds only; a fixed value has to be representable.
    stamp = stamp[:5] + (stamp[5] - stamp[5] % 2,)
    return max(stamp, _ZIP_FLOOR)


def _entry_order(names: list[str]) -> list[str]:
    """A fixed order: `mimetype` first (ODF/EPUB need it), then the OPC
    content-types part (every Office reader looks there first), then the rest
    sorted by name."""
    head = [n for n in ("mimetype", "[Content_Types].xml") if n in names]
    return head + sorted(n for n in names if n not in head)


def normalise_core_properties(xml: bytes, epoch: int) -> bytes:
    """Set the created/modified properties to the epoch, in the W3CDTF form
    the part declares (xsi:type="dcterms:W3CDTF")."""
    moment = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ").encode("ascii")
    return _CORE_TIMES.sub(lambda m: m.group(1) + moment + m.group(3), xml)


def normalise_zip(path: Path, epoch: int) -> None:
    """Rewrite the archive with every entry stamped at `epoch`, in a fixed
    order, with fixed attributes and no archive comment, and its Office
    created/modified properties set to `epoch`."""
    stamp = _zip_time(epoch)
    with zipfile.ZipFile(path) as src:
        names = [i.filename for i in src.infolist()]
        if len(set(names)) != len(names):
            raise ValueError(f"{path}: archive holds a duplicate entry name; refusing to choose one")
        entries = {i.filename: (i, src.read(i.filename)) for i in src.infolist()}

    tmp = path.with_name(path.name + ".normalising")
    with zipfile.ZipFile(tmp, "w") as dst:
        for name in _entry_order(names):
            original, payload = entries[name]
            if name == _CORE_PART:
                payload = normalise_core_properties(payload, epoch)
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.create_system = 3
            is_dir = name.endswith("/")
            info.external_attr = ((0o40755 if is_dir else 0o100644) << 16) | (0x10 if is_dir else 0)
            # `mimetype` must be stored, not deflated, where it is present.
            stored = name == "mimetype" or original.compress_type == zipfile.ZIP_STORED
            info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
            dst.writestr(info, payload, compresslevel=None if stored else 9)
    tmp.replace(path)


def normalise(path: Path, epoch: int) -> None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        data = path.read_bytes()
        out = normalise_pdf_bytes(data)
        if out != data:
            path.write_bytes(out)
    elif suffix in ZIP_SUFFIXES:
        normalise_zip(path, epoch)
    else:
        raise ValueError(f"{path}: no normalisation is defined for '{suffix}' files")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--epoch", required=True, type=int, help="SOURCE_DATE_EPOCH, in seconds")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if args.epoch < 0:
        parser.error("--epoch must not be negative")
    for f in args.files:
        if not f.is_file():
            print(f"error: {f}: not a file", file=sys.stderr)
            return 1
        try:
            normalise(f, args.epoch)
        except (ValueError, zipfile.BadZipFile) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
