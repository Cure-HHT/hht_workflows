"""Write the deliverables: a deterministic CSV extract and the workbook."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .manifest import Manifest
from .pivot import CARRIED_SUFFIX, FAIL, NOT_RUN, PASS

#: Column-width bounds applied to every sheet, in Excel's character-count
#: width unit. MIN keeps a column of short values (a verdict, a short id)
#: from reading as a sliver next to its header. MAX caps how far a single
#: long value -- a requirement title, a legend paragraph -- can stretch its
#: column; content past the cap relies on wrap_text (set below) rather than
#: sheet width, so one outlier cell cannot make the whole sheet unwieldy.
_MIN_COLUMN_WIDTH = 10
_MAX_COLUMN_WIDTH = 50
_WIDTH_PADDING = 2

#: Font colours for verdict cells, matched by exact value rather than column
#: position. Chosen dark and muted rather than pure FF0000/00FF00: legible on
#: a white background and, since colour is an aid and the verdict text itself
#: carries the distinction, legible (not necessarily distinguishable from
#: each other) when printed in greyscale. These are the same hex values
#: Excel's own built-in "Light Red/Green Fill with Dark Red/Green Text"
#: conditional-formatting styles use for the same PASS/FAIL convention.
_FAIL_FONT_COLOR = "9C0006"
_PASS_FONT_COLOR = "006100"

#: The organisation that produces these reports. Fixed across every
#: consumer -- unlike the sponsor, it is not something a manifest declares
#: or a repo-relative file states, so it is a constant here rather than a
#: field threaded through Manifest/Provenance.
VENDOR_NAME = "Anspar Foundation"


@dataclass(frozen=True)
class Provenance:
    primary_commit: str
    associate_commits: tuple[str, ...]
    elspais_version: str
    tool_version: str
    scope_name: str
    scope_lines: tuple[str, ...]
    generated_at: str
    req_count: int
    uat_count: int
    #: The sponsor's legal name, read from the consuming repo's
    #: sponsor-info.yaml. None when that file (or its urs_manifest
    #: declaration, or the sponsor_name key) is absent -- the Sponsor row is
    #: then omitted rather than shown empty or with a placeholder.
    sponsor_name: str | None = None
    #: The study protocol number, read from the same sponsor-info.yaml's
    #: protocol_number key. Independently optional of protocol_version and
    #: sponsor_name -- a file naming this but not the others yields only
    #: this row.
    protocol_number: str | None = None
    #: The study protocol version, read from the same sponsor-info.yaml's
    #: protocol_version key. Independently optional of protocol_number and
    #: sponsor_name -- a file naming this but not the others yields only
    #: this row.
    protocol_version: str | None = None


def _headers(columns: tuple[str, ...], width: int) -> list[str]:
    """Extend the declared header to the widest row.

    The last declared column repeats: rows carry a variable number of
    journeys (or requirements), each in its own column, and every one of them
    is the same kind of thing.
    """
    if not columns:
        return [""] * width
    header = list(columns)
    while len(header) < width:
        header.append(columns[-1])
    return header[:width] if width else header


def write_csv(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    """Write the extract that is committed and diffed.

    Every row is padded to the widest, so the file is a rectangle and a diff
    reports a changed cell rather than a reshaped row. Newlines are fixed to
    "\\n" so the bytes do not depend on the platform that produced them.
    """
    width = max([len(header), *(len(r) for r in rows)] or [len(header)])
    with Path(path).open("w", newline="\n", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(_headers(header, width))
        for row in rows:
            writer.writerow(list(row) + [""] * (width - len(row)))


def _column_definition_rows(manifest: Manifest) -> list[list[str]]:
    """Define every column on the two grid sheets, named as the manifest
    declares them so a renamed column keeps a definition that matches it.

    Covers the fixed columns and states, for the repeating trailing column
    on each sheet, what one instance of it holds.
    """
    req_id_col, req_title_col, test_column, uat_column, req_journey_col = (
        manifest.req_columns_without_section()
    )
    uat_id_col, uat_title_col, uat_verdict_col, uat_journey_col, uat_req_col = (
        manifest.uat_sheet.columns
    )
    return [
        ["Column definitions"],
        [],
        [f"{manifest.req_sheet.name} sheet"],
        [req_id_col, "The requirement's id."],
        *(
            [[
                manifest.req_section_column,
                "The number of the User Requirements Specification section "
                "this requirement appears in. Empty when the requirement "
                "appears in no section of that document.",
            ]]
            if manifest.req_section_column is not None
            else []
        ),
        [req_title_col, "The requirement's title."],
        [
            test_column,
            "Test-verification verdict: did this requirement's own tests "
            "pass? See the legend below.",
        ],
        [
            uat_column,
            "User-acceptance verdict: did a user journey validating this "
            "requirement pass? See the legend below.",
        ],
        [
            req_journey_col,
            "Repeats once per validating test case; each cell holds one "
            "validating test-case identifier.",
        ],
        [],
        [f"{manifest.uat_sheet.name} sheet"],
        [uat_id_col, "The test case's identifier."],
        [uat_title_col, "The test case's title."],
        [uat_verdict_col, "The test case's verdict. See the legend below."],
        [uat_journey_col, "The identifier of the source user journey."],
        [
            uat_req_col,
            "Repeats once per validated requirement; each cell holds one "
            "requirement id this test case validates.",
        ],
    ]


def _provenance_rows(manifest: Manifest, prov: Provenance) -> list[list[str]]:
    # The legend names the two verdict columns by the titles the manifest
    # declares, so a consumer that renames them keeps a legend that matches
    # its own sheet. The manifest guarantees both are present.
    test_column, uat_column = manifest.req_columns_without_section()[2:4]
    identity_rows: list[list[str]] = [
        ["Report", manifest.title],
    ]
    if prov.protocol_number:
        identity_rows.append(["Protocol number", prov.protocol_number])
    if prov.protocol_version:
        identity_rows.append(["Protocol version", prov.protocol_version])
    identity_rows.append(["Project", manifest.project])
    identity_rows.append(["Vendor", VENDOR_NAME])
    if prov.sponsor_name:
        identity_rows.append(["Sponsor", prov.sponsor_name])
    identity_rows.append([])
    return [
        *identity_rows,
        ["Generated at (UTC)", prov.generated_at],
        [],
        ["Scope name", prov.scope_name],
        *[["Scope", line] for line in prov.scope_lines],
        ["Requirements reported", str(prov.req_count)],
        ["UAT test cases reported", str(prov.uat_count)],
        [],
        ["Primary repository commit", prov.primary_commit],
        *[["Associate repository commit", c] for c in prov.associate_commits],
        ["elspais version", prov.elspais_version],
        ["Generator version", prov.tool_version],
        [],
        *_column_definition_rows(manifest),
        [],
        ["Verdict legend"],
        [
            "",
            "Each requirement carries two independent kinds of evidence, in "
            "two columns. They are reported separately and never combined, so "
            "a reader can see which kind of evidence is absent or failing.",
        ],
        [
            "",
            f"Wherever a verdict cell holds one of these values, {PASS} is "
            f"shown in green text and {FAIL} in red; {NOT_RUN} is left "
            "unstyled because it reports an absence of evidence, not an "
            "outcome.",
        ],
        [],
        [
            test_column,
            "Did this requirement's own tests (unit, integration, end-to-end) "
            "pass?",
        ],
        [
            f"{test_column}: {PASS}",
            "Every assertion of the requirement is verified by a passing test.",
        ],
        [
            f"{test_column}: {FAIL}",
            "At least one test citing this requirement failed.",
        ],
        [
            f"{test_column}: {NOT_RUN}",
            "No test result has been ingested for this requirement, or only "
            "some of its assertions are verified by a passing test. A test "
            "that exists but whose result has not been ingested reports here, "
            "never as a failure: absence of evidence is not evidence of "
            "failure.",
        ],
        [
            f"{test_column}:{CARRIED_SUFFIX}",
            "The verification was carried forward from a baseline rather than "
            "produced by a fresh run, and is a weaker claim than an unmarked "
            "verdict.",
        ],
        [],
        [
            uat_column,
            "Did a user journey validating this requirement pass?",
        ],
        [
            f"{uat_column}: {PASS}",
            "Every assertion the requirement expects is verified, and no "
            "validating journey failed.",
        ],
        [
            f"{uat_column}: {FAIL}",
            "At least one validating journey failed.",
        ],
        [
            f"{uat_column}: {NOT_RUN}",
            "No validating journey has been run, or journey coverage is "
            "partial. Not a failure.",
        ],
        [],
        [
            "",
            f"The two {NOT_RUN} entries are different absences: the first "
            "means no test result has been ingested, the second means no "
            "validating journey has been run. Neither is a failure.",
        ],
    ]


def _size_columns_to_content(ws: Worksheet, rows: list[list[str]]) -> None:
    """Set each column's width from the longest value actually in it,
    clamped to [_MIN_COLUMN_WIDTH, _MAX_COLUMN_WIDTH]."""
    n_cols = max((len(r) for r in rows), default=0)
    for idx in range(n_cols):
        longest = max(
            (len(str(r[idx])) for r in rows if idx < len(r) and r[idx] is not None),
            default=0,
        )
        width = max(_MIN_COLUMN_WIDTH, min(longest + _WIDTH_PADDING, _MAX_COLUMN_WIDTH))
        ws.column_dimensions[get_column_letter(idx + 1)].width = width


def _wrap_all_cells(ws: Worksheet) -> None:
    """Turn on wrapping everywhere content exceeding the (capped) column
    width would otherwise be clipped.

    openpyxl cannot compute a fitted row height -- there is no text-layout
    engine behind it -- so row heights are left at the viewer's default and
    the viewer (Excel, Sheets, ...) grows them to fit on open/edit.
    """
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def _bold_header_row(ws: Worksheet) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True)


def _colour_verdict_cells(ws: Worksheet) -> None:
    """Colour a verdict cell by its exact value: red text for FAIL, green
    text for PASS. NOT_RUN is left entirely unstyled -- it reports an
    absence of evidence, not an outcome.

    Matched on value rather than column position: the requirement sheet
    carries two verdict columns (test-verification and UAT), the test-case
    sheet carries one, and this stays correct if either sheet's columns are
    ever reordered.
    """
    for row in ws.iter_rows():
        for cell in row:
            if cell.value == FAIL:
                cell.font = Font(color=_FAIL_FONT_COLOR)
            elif cell.value == PASS:
                cell.font = Font(color=_PASS_FONT_COLOR)


def _set_autofilter(ws: Worksheet, n_cols: int, n_rows: int) -> None:
    """Add filter/sort dropdowns to the header row, ranged over the sheet's
    actual used extent.

    Both grid sheets have a variable number of trailing columns (one per
    journey or per validated requirement), so the range is computed from the
    written content rather than a hardcoded column letter.
    """
    last_col = get_column_letter(max(n_cols, 1))
    last_row = max(n_rows, 1)
    ws.auto_filter.ref = f"A1:{last_col}{last_row}"


def _bold_provenance_labels(ws: Worksheet, rows: list[list[str]]) -> None:
    """Bold column A wherever it holds a label or heading.

    The provenance sheet reads throughout as label/value pairs -- plain
    facts ("Report", "Project"), section headings ("Column definitions",
    "Verdict legend"), and column/legend-entry names alike sit in column A,
    so bolding it uniformly bolds every one of them and nothing else (rows
    that are pure explanatory prose keep column A blank).
    """
    for idx, row in enumerate(rows, start=1):
        if row and row[0]:
            ws.cell(row=idx, column=1).font = Font(bold=True)


def _merge_and_center_block_headings(ws: Worksheet, rows: list[list[str]]) -> None:
    """Merge A:B and centre each block-heading row.

    A block heading -- "Column definitions", a sheet-name heading introducing
    that sheet's column definitions, "Verdict legend" -- is authored with no
    column-B slot at all: a one-element row, rather than a label/value pair.
    Every other row, including blank separators and the two rows of pure
    explanatory prose (column A blank, column B holding the sentence), keeps
    its two-column left-aligned form. Detecting the row's arity rather than
    matching specific heading text keeps this correct for the two headings
    the manifest supplies as sheet names, not just the ones defined in this
    module -- and does not misfire on a fact row (e.g. a commit hash) whose
    *value* happens to be an empty string.
    """
    for idx, row in enumerate(rows, start=1):
        if row and row[0] and len(row) < 2:
            ws.merge_cells(start_row=idx, start_column=1, end_row=idx, end_column=2)
            ws.cell(row=idx, column=1).alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )


def write_workbook(
    path: Path,
    manifest: Manifest,
    req_rows_: list[list[str]],
    uat_rows_: list[list[str]],
    provenance: Provenance,
) -> None:
    """Write the three-sheet workbook, provenance first.

    Not committed: a workbook embeds creation and modification times and
    per-entry archive timestamps, so two with identical content differ byte
    for byte. It is uploaded as an artifact bound to the run instead.
    """
    wb = Workbook()

    prov = wb.active
    prov.title = manifest.provenance_sheet_name
    prov_rows = _provenance_rows(manifest, provenance)
    for row in prov_rows:
        prov.append(row)
    _bold_provenance_labels(prov, prov_rows)
    _wrap_all_cells(prov)
    _merge_and_center_block_headings(prov, prov_rows)
    _size_columns_to_content(prov, prov_rows)

    # Freeze panes on the two grid sheets only: each is wide (a variable
    # number of trailing journey/requirement columns) and long (hundreds of
    # rows), so a reader scrolling right loses the header and a reader
    # scrolling down loses the row's identifying first column. The
    # provenance sheet is a label/value list, not a grid, and freezing there
    # would be noise.
    req = wb.create_sheet(manifest.req_sheet.name)
    req_width = max([len(manifest.req_sheet.columns), *(len(r) for r in req_rows_)] or [0])
    req_header = _headers(manifest.req_sheet.columns, req_width)
    req.append(req_header)
    for row in req_rows_:
        req.append(row)
    _bold_header_row(req)
    _colour_verdict_cells(req)
    _wrap_all_cells(req)
    _size_columns_to_content(req, [req_header, *req_rows_])
    req.freeze_panes = "B2"
    _set_autofilter(req, req_width, 1 + len(req_rows_))

    uat = wb.create_sheet(manifest.uat_sheet.name)
    uat_width = max([len(manifest.uat_sheet.columns), *(len(r) for r in uat_rows_)] or [0])
    uat_header = _headers(manifest.uat_sheet.columns, uat_width)
    uat.append(uat_header)
    for row in uat_rows_:
        uat.append(row)
    _bold_header_row(uat)
    _colour_verdict_cells(uat)
    _wrap_all_cells(uat)
    _size_columns_to_content(uat, [uat_header, *uat_rows_])
    uat.freeze_panes = "B2"
    _set_autofilter(uat, uat_width, 1 + len(uat_rows_))

    wb.save(Path(path))
