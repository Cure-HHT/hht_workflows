"""Turn requirements-with-journeys into the two sheets, in both directions."""

from __future__ import annotations

from typing import Mapping

from .load import Requirement
from .manifest import SECTION_COLUMN_INDEX, Manifest

PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT RUN"

#: Appended to a test result whose verification came from a carried baseline
#: rather than a fresh run. A carried value is a weaker claim than a fresh one,
#: and it is a per-requirement property, so it is marked on the cell it
#: qualifies rather than summarised on the provenance sheet.
CARRIED_SUFFIX = " (carried)"

_FAIL_VERDICTS = frozenset({"fail", "failed", "failure", "error"})
_PASS_VERDICTS = frozenset({"pass", "passed", "success"})


def journey_verdict(verdict: str) -> str:
    """Render one journey's verdict.

    Anything that is neither a pass nor a fail — `unverified` above all — is
    NOT RUN. An absence of evidence is never reported as a failure: a
    premature red is worse than an honest blank.
    """
    lowered = (verdict or "").strip().lower()
    if lowered in _FAIL_VERDICTS:
        return FAIL
    if lowered in _PASS_VERDICTS:
        return PASS
    return NOT_RUN


def requirement_verdict(req: Requirement) -> str:
    """Roll a requirement's journeys up to one verdict.

    FAIL if any validating journey failed. PASS only when every assertion the
    requirement expects is verified — a partly-covered requirement has not
    been validated, whatever its journeys say. NOT RUN otherwise.
    """
    if any(journey_verdict(j.verdict) == FAIL for j in req.journeys):
        return FAIL
    if req.journeys and req.uat_verified_ratio >= 1.0:
        return PASS
    return NOT_RUN


def verification_verdict(req: Requirement) -> str:
    """Roll a requirement's test-verification evidence up to one verdict.

    Deliberately asymmetric, mirroring `requirement_verdict`:

    FAIL when at least one test citing the requirement failed. PASS only when
    every assertion is verified by a passing test -- partial verification is
    not a pass. NOT RUN otherwise, which includes the `awaiting` case: a test
    that exists but whose result has never been ingested is an absence of
    evidence, not evidence of failure, and must never render as FAIL.

    Returns one of the three labels only; the carried-baseline caveat is
    rendered by the caller, so callers reasoning about the verdict itself
    compare against a bare label.
    """
    if req.tested_failed > 0:
        return FAIL
    if req.verified_ratio >= 1.0:
        return PASS
    return NOT_RUN


def rendered_verification_verdict(req: Requirement) -> str:
    """The test verdict as it appears in the cell, carried baselines marked.

    A carried value satisfies the same threshold as a fresh one but rests on a
    previous run, so the cell states it. Marking it here rather than on the
    provenance sheet keeps the caveat attached to the requirement it qualifies:
    a provenance note cannot name which rows are carried, and the extract is
    committed and diffed, so a carried-to-fresh transition shows up as the cell
    change it is.
    """
    verdict = verification_verdict(req)
    return f"{verdict}{CARRIED_SUFFIX}" if req.verified_carried else verdict


def req_rows(
    reqs: tuple[Requirement, ...],
    manifest: Manifest,
    sections: Mapping[str, str] | None = None,
) -> list[list[str]]:
    """One row per requirement: id, title, test result, UAT result, then one
    journey per column.

    When the manifest names a URS manifest, the row also carries the number
    of the URS section the requirement appears in, in the position the row
    shape fixes. ``sections`` maps requirement id to section number; a
    requirement the URS places in no section is absent from it and its cell
    is left empty. An empty cell states that the requirement appears in no
    section, which is honest; a guessed number in a regulatory column is not.

    The two verdicts are stated side by side and never combined. They answer
    different questions -- did this requirement's tests pass, and did a
    validating journey pass -- and a regulator must be able to see which kind
    of evidence is absent or failing. A single rolled-up verdict cannot say.

    Each journey column carries the same `UAT Test Case ID` header as the UAT
    sheet's identifier column, so it must hold the same value: the journey id
    under the manifest's configured case prefix, not the raw journey id.

    The journey columns are sorted by journey id, as `uat_rows` sorts its
    requirement columns. Upstream array order is not a documented guarantee,
    and the CSV extract is committed and diffed: a reordering upstream would
    otherwise show up as a spurious evidence change.
    """
    lookup = sections or {}
    with_section = manifest.req_section_column is not None
    rows: list[list[str]] = []
    for r in sorted(reqs, key=lambda r: r.id):
        row = [
            r.id,
            r.title,
            rendered_verification_verdict(r),
            requirement_verdict(r),
            *[
                f"{manifest.uat_case_prefix}{j.id}"
                for j in sorted(r.journeys, key=lambda j: j.id)
            ],
        ]
        if with_section:
            row.insert(SECTION_COLUMN_INDEX, lookup.get(r.id, ""))
        rows.append(row)
    return rows


def uat_rows(
    reqs: tuple[Requirement, ...],
    journey_titles: dict[str, str],
    manifest: Manifest,
) -> list[list[str]]:
    """One row per journey: case id, title, verdict, journey id, then one
    requirement per column.

    Membership is derived: a journey appears because it validates a
    requirement in scope. A journey validating nothing in scope has no
    traceability to report and no row here.

    Raises ValueError if a journey is cited by multiple requirements with
    conflicting verdicts, as that indicates upstream data integrity drift.
    """
    validated: dict[str, list[str]] = {}
    verdicts: dict[str, str] = {}
    verdict_sources: dict[str, str] = {}  # Track which requirement first recorded each verdict
    for req in sorted(reqs, key=lambda r: r.id):
        for ref in req.journeys:
            validated.setdefault(ref.id, []).append(req.id)
            if ref.id not in verdicts:
                verdicts[ref.id] = ref.verdict
                verdict_sources[ref.id] = req.id
            else:
                # Check for conflict: compare normalized verdicts
                if journey_verdict(ref.verdict) != journey_verdict(verdicts[ref.id]):
                    raise ValueError(
                        f"Journey {ref.id} cited by {verdict_sources[ref.id]} "
                        f"(verdict: {verdicts[ref.id]}) and {req.id} "
                        f"(verdict: {ref.verdict}) with conflicting verdicts"
                    )

    return [
        [
            f"{manifest.uat_case_prefix}{jid}",
            journey_titles.get(jid, ""),
            journey_verdict(verdicts[jid]),
            jid,
            *validated[jid],
        ]
        for jid in sorted(validated)
    ]
