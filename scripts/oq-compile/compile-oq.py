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

from oq_compile.load import Requirement, load_journeys, load_trace  # noqa: E402
from oq_compile.manifest import Manifest  # noqa: E402
from oq_compile.pivot import req_rows, uat_rows  # noqa: E402
from oq_compile.render import Provenance, write_csv, write_workbook  # noqa: E402
from oq_compile.urs_sections import (  # noqa: E402
    resolve_urs_manifest_path,
    section_numbers,
)


def _namespace(req_id: str) -> str:
    """The requirement-id namespace: everything before the first hyphen."""
    return req_id.split("-", 1)[0]


def check_required_namespaces(
    requirements: tuple[Requirement, ...], manifest: Manifest
) -> None:
    """Refuse a selection missing a namespace the manifest declares.

    A federated report draws its rows from the consuming repo plus its
    associates. Nothing in the trace states which associates were meant to be
    present, so a run with an associate unconfigured yields a well-formed,
    correctly-provenanced report holding only the consumer's own requirements
    -- a fraction of the evidence, at exit 0, with every other guard passing.

    ``require_namespaces`` is the manifest's assertion about membership, so it
    is not covered by ``--allow-empty``: an empty report may be honest, but a
    report missing a namespace the sponsor declared never is. Declaring
    nothing keeps today's behaviour, so consumers that do not federate are
    unaffected.
    """
    if not manifest.require_namespaces:
        return
    found = sorted({_namespace(r.id) for r in requirements})
    missing = [ns for ns in manifest.require_namespaces if ns not in found]
    if missing:
        raise ValueError(
            "requirement namespace(s) declared by the manifest are absent "
            f"from the selection: missing {missing}; found {found or ['(none)']}; "
            f"expected {list(manifest.require_namespaces)}. Refusing to write a "
            "partial report -- an associate repository is most likely not "
            "federated for this run."
        )


def build(
    manifest_path: Path,
    trace_path: Path,
    graph_path: Path,
    out_csv_dir: Path,
    out_xlsx: Path,
    provenance_overrides: dict[str, Any] | None = None,
    allow_empty: bool = False,
    primary_root: Path | None = None,
) -> tuple[int, int]:
    """Produce both deliverables. Returns (requirement count, UAT case count).

    Refuses to write anything when the trace selects zero requirements or
    yields zero UAT test cases, unless ``allow_empty`` is set: a well-formed, correctly-provenanced,
    entirely empty report is indistinguishable from a healthy report on a
    tiny scope, and is exactly the shape a loader bug or a manifest typo
    produces. Checked here rather than in the CLI entrypoint so no caller
    of ``build()`` -- including a future one -- can bypass it.
    """
    overrides = dict(provenance_overrides or {})
    manifest = Manifest.from_path(Path(manifest_path))
    requirements, scope_lines = load_trace(Path(trace_path))

    check_required_namespaces(requirements, manifest)

    if not requirements and not allow_empty:
        raise ValueError(
            f"no requirements matched scope '{manifest.scope}'; refusing to "
            "write an empty report. Pass --allow-empty (build(allow_empty=True) "
            "when calling build() directly) if an empty report is genuinely "
            "expected."
        )

    cited_journeys = sum(len(r.journeys) for r in requirements)
    journey_titles = load_journeys(Path(graph_path), cited_journeys)

    # The URS-section column is optional: a consumer that publishes no URS
    # declares no URS manifest and gets a report without it. Declaring one
    # that cannot be read is an error, not a blank column.
    sections: dict[str, str] = {}
    if manifest.urs_manifest:
        sections = section_numbers(
            resolve_urs_manifest_path(
                manifest.urs_manifest, Path(manifest_path), primary_root
            ),
            Path(graph_path),
        )

    rows_req = req_rows(requirements, manifest, sections)
    rows_uat = uat_rows(requirements, journey_titles, manifest)

    if not rows_uat and not allow_empty:
        raise ValueError(
            f"scope '{manifest.scope}' selected {len(rows_req)} requirement(s) "
            "but no UAT test case; refusing to write a report whose UAT sheet "
            "is empty. Counting requirements alone does not catch this: a "
            "dropped or renamed journeys key yields a full REQ sheet and an "
            "empty UAT sheet. Pass --allow-empty (build(allow_empty=True) when "
            "calling build() directly) if that is genuinely expected."
        )

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
        "--primary-root",
        type=Path,
        default=None,
        help=(
            "Root of the consuming repository, used to resolve the "
            "repo-relative URS manifest the OQ manifest may declare. "
            "Omitted, the OQ manifest's own directory and its parents are "
            "searched instead."
        ),
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help=(
            "Permit writing a report with zero requirements or zero UAT "
            "test cases. Refused by default: a well-formed empty report is "
            "what a loader bug or a wrong scope produces, silently."
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
        primary_root=args.primary_root,
    )
    print(f"OQ report: {reqs} requirements, {cases} UAT test cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
