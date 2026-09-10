#!/usr/bin/env python3
"""Build the OQ traceability deliverables from elspais output.

Invoked by oq-compile.sh, which produces the two JSON inputs. Kept separate so
the pipeline can be exercised on fixtures without running elspais.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from oq_compile.load import load_journeys, load_trace  # noqa: E402
from oq_compile.manifest import Manifest  # noqa: E402
from oq_compile.pivot import req_rows, uat_rows  # noqa: E402
from oq_compile.render import Provenance, write_csv, write_workbook  # noqa: E402


def build(
    manifest_path: Path,
    trace_path: Path,
    graph_path: Path,
    out_csv_dir: Path,
    out_xlsx: Path,
    provenance_overrides: dict[str, Any] | None = None,
    allow_empty: bool = False,
) -> tuple[int, int]:
    """Produce both deliverables. Returns (requirement count, UAT case count).

    Refuses to write anything when the trace selects zero requirements,
    unless ``allow_empty`` is set: a well-formed, correctly-provenanced,
    entirely empty report is indistinguishable from a healthy report on a
    tiny scope, and is exactly the shape a loader bug or a manifest typo
    produces. Checked here rather than in the CLI entrypoint so no caller
    of ``build()`` -- including a future one -- can bypass it.
    """
    overrides = dict(provenance_overrides or {})
    manifest = Manifest.from_path(Path(manifest_path))
    requirements, scope_lines = load_trace(Path(trace_path))
    journey_titles = load_journeys(Path(graph_path))

    if not requirements and not allow_empty:
        raise ValueError(
            f"no requirements matched scope '{manifest.scope}'; refusing to "
            "write an empty report. Pass --allow-empty (build(allow_empty=True) "
            "when calling build() directly) if an empty report is genuinely "
            "expected."
        )

    rows_req = req_rows(requirements, manifest)
    rows_uat = uat_rows(requirements, journey_titles, manifest)

    provenance = Provenance(
        primary_commit=overrides.get("primary_commit", ""),
        associate_commits=tuple(overrides.get("associate_commits", ())),
        elspais_version=overrides.get("elspais_version", ""),
        tool_version=overrides.get("tool_version", ""),
        scope_name=manifest.scope,
        scope_lines=tuple(overrides.get("scope_lines", scope_lines)),
        generated_at=overrides.get(
            "generated_at",
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
        req_count=len(rows_req),
        uat_count=len(rows_uat),
    )

    csv_dir = Path(out_csv_dir)
    csv_dir.mkdir(parents=True, exist_ok=True)
    write_csv(csv_dir / "oq-req.csv", manifest.req_sheet.columns, rows_req)
    write_csv(csv_dir / "oq-uat.csv", manifest.uat_sheet.columns, rows_uat)

    xlsx = Path(out_xlsx)
    xlsx.parent.mkdir(parents=True, exist_ok=True)
    write_workbook(xlsx, manifest, rows_req, rows_uat, provenance)

    return len(rows_req), len(rows_uat)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--out-csv-dir", required=True, type=Path)
    parser.add_argument("--out-xlsx", required=True, type=Path)
    parser.add_argument("--primary-commit", default="")
    parser.add_argument("--associate-commit", action="append", default=[])
    parser.add_argument("--elspais-version", default="")
    parser.add_argument("--tool-version", default="")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help=(
            "Permit writing a report with zero requirements. Refused by "
            "default: a well-formed empty report is what a loader bug or a "
            "wrong scope produces, silently."
        ),
    )
    args = parser.parse_args()

    reqs, cases = build(
        manifest_path=args.manifest,
        trace_path=args.trace,
        graph_path=args.graph,
        out_csv_dir=args.out_csv_dir,
        out_xlsx=args.out_xlsx,
        provenance_overrides={
            "primary_commit": args.primary_commit,
            "associate_commits": tuple(args.associate_commit),
            "elspais_version": args.elspais_version,
            "tool_version": args.tool_version,
        },
        allow_empty=args.allow_empty,
    )
    print(f"OQ report: {reqs} requirements, {cases} UAT test cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
