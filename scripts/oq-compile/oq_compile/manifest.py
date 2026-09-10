"""Load and validate the sponsor-supplied OQ manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_UAT_PREFIX = "UAT-"

#: The REQ sheet's declared header: requirement id, description, test result,
#: UAT result, then the journey column that repeats once per validating
#: journey. Declared rather than inferred so a manifest written against the
#: older single-verdict shape is refused instead of silently mislabelled.
_REQ_SHEET_COLUMNS = 5

#: The UAT sheet's declared header: test-case id, description, verdict,
#: source journey id, then the requirement column that repeats once per
#: validated requirement. Enforced for the same reason as the REQ count: the
#: renderer's provenance-sheet column definitions index into this tuple by
#: fixed position (`columns[0..3]`, `columns[-1]`), so an under-declared
#: manifest must be refused here rather than raise deep inside rendering.
_UAT_SHEET_COLUMNS = 5

_DEFAULT_PROVENANCE_NAME = "Provenance"


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    """Return ``mapping[key]``, or fail loud naming ``ctx``."""
    if key not in mapping or mapping[key] is None:
        raise ValueError(f"{ctx}: required key '{key}' is missing")
    return mapping[key]


def _coerce_namespaces(raw: Any, ctx: str) -> tuple[str, ...]:
    """Validate a ``require_namespaces:`` value and return it as a tuple.

    Optional: a manifest that declares nothing keeps the generator agnostic
    about who is federated, which is what every consumer but this one wants.
    A bare scalar would silently become a tuple of characters naming no
    namespace, so require a list of strings and fail loud.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
        raise ValueError(
            f"{ctx}: 'require_namespaces' must be a list of non-empty strings, "
            f"got {raw!r}"
        )
    return tuple(raw)


def _coerce_columns(raw: Any, ctx: str) -> tuple[str, ...]:
    """Validate a ``columns:`` value and return it as a tuple.

    A ``columns:`` written as a bare scalar would otherwise be silently
    turned into a tuple of characters that names no column; require a list
    of strings and fail loud, naming ``ctx``.
    """
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError(f"{ctx}: 'columns' must be a list of strings, got {raw!r}")
    return tuple(raw)


@dataclass(frozen=True)
class SheetSpec:
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    title: str
    project: str
    scope: str
    uat_case_prefix: str
    require_namespaces: tuple[str, ...]
    req_sheet: SheetSpec
    uat_sheet: SheetSpec
    provenance_sheet_name: str

    @classmethod
    def from_path(cls, path: Path) -> Manifest:
        raw = yaml.safe_load(Path(path).read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: manifest must be a mapping, got {type(raw).__name__}")

        document = _require(raw, "document", str(path))
        sheets = _require(raw, "sheets", str(path))

        def sheet(key: str, default_name: str) -> SheetSpec:
            spec = _require(sheets, key, f"{path}: sheets")
            return SheetSpec(
                name=str(spec.get("name", default_name)),
                columns=_coerce_columns(
                    _require(spec, "columns", f"{path}: sheets.{key}"),
                    f"{path}: sheets.{key}",
                ),
            )

        req_sheet = sheet("req", "REQ")
        if len(req_sheet.columns) != _REQ_SHEET_COLUMNS:
            # The renderer repeats the last declared column to reach the widest
            # row. A manifest still declaring the older four-column REQ header
            # would therefore label the UAT-result column with the journey
            # column's title -- a wrong header over real verdicts, silently.
            raise ValueError(
                f"{path}: sheets.req 'columns' must declare exactly "
                f"{_REQ_SHEET_COLUMNS} columns -- requirement id, description, "
                "test result, UAT result, and the journey column that repeats "
                f"once per validating journey -- got {len(req_sheet.columns)}: "
                f"{list(req_sheet.columns)}"
            )

        uat_sheet = sheet("uat", "UAT Test Cases")
        if len(uat_sheet.columns) != _UAT_SHEET_COLUMNS:
            # Mirrors the REQ-sheet check above: the provenance sheet's
            # column-definitions section and the CSV/workbook renderers both
            # index into this tuple by fixed position, so an under- or
            # over-declared UAT header must be refused here, loud, rather
            # than reach an IndexError deep inside rendering.
            raise ValueError(
                f"{path}: sheets.uat 'columns' must declare exactly "
                f"{_UAT_SHEET_COLUMNS} columns -- test-case id, description, "
                "verdict, source journey id, and the requirement column that "
                f"repeats once per validated requirement -- got "
                f"{len(uat_sheet.columns)}: {list(uat_sheet.columns)}"
            )

        provenance = sheets.get("provenance") or {}
        return cls(
            title=str(_require(document, "title", f"{path}: document")),
            project=str(_require(document, "project", f"{path}: document")),
            scope=str(_require(raw, "scope", str(path))),
            uat_case_prefix=str(raw.get("uat_case_prefix", _DEFAULT_UAT_PREFIX)),
            require_namespaces=_coerce_namespaces(
                raw.get("require_namespaces"), str(path)
            ),
            req_sheet=req_sheet,
            uat_sheet=uat_sheet,
            provenance_sheet_name=str(
                provenance.get("name", _DEFAULT_PROVENANCE_NAME)
            ),
        )
