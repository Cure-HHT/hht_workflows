from __future__ import annotations

import pytest

from oq_compile.load import JourneyRef, Requirement, load_journeys, load_trace
from oq_compile.manifest import Manifest
from oq_compile.pivot import (
    CARRIED_SUFFIX,
    FAIL,
    NOT_RUN,
    PASS,
    rendered_verification_verdict,
    req_rows,
    requirement_verdict,
    uat_rows,
    verification_verdict,
)


def _req(
    rid,
    ratio,
    journeys,
    verified_ratio=0.0,
    verified_carried=False,
    tested_failed=0.0,
):
    return Requirement(
        id=rid, title=rid.title(), level="PRD", status="Draft",
        uat_verified_ratio=ratio,
        verified_ratio=verified_ratio,
        verified_carried=verified_carried,
        tested_failed=tested_failed,
        journeys=tuple(journeys),
    )


def test_verdict_pass_when_fully_verified():
    r = _req("SPN-PRD-a", 1.0, [JourneyRef("JNY-1", "pass")])
    assert requirement_verdict(r) == PASS


def test_verdict_fail_when_any_journey_failed():
    r = _req("SPN-PRD-a", 1.0, [JourneyRef("JNY-1", "pass"), JourneyRef("JNY-2", "fail")])
    assert requirement_verdict(r) == FAIL


def test_unverified_is_not_run_never_fail():
    r = _req("SPN-PRD-a", 0.0, [JourneyRef("JNY-1", "unverified")])
    assert requirement_verdict(r) == NOT_RUN


def test_partial_coverage_is_not_run():
    r = _req("SPN-PRD-a", 0.5, [JourneyRef("JNY-1", "pass")])
    assert requirement_verdict(r) == NOT_RUN


def test_no_journeys_is_not_run():
    assert requirement_verdict(_req("SPN-PRD-a", 0.0, [])) == NOT_RUN


def test_req_rows_have_variable_width(sample_trace_path, sample_manifest_path):
    reqs, _ = load_trace(sample_trace_path)
    m = Manifest.from_path(sample_manifest_path)
    rows = req_rows(reqs, m)
    by_id = {r[0]: r for r in rows}
    assert by_id["SPN-PRD-session-management"][4:] == ["UAT-JNY-AUTH-06"]
    # Sorted by journey id, not by the order the trace happened to list them
    # (the fixture lists EPIS-10 first). The extract is committed and diffed,
    # so an upstream reordering must not read as an evidence change.
    assert by_id["SPN-GUI-calendar-day-view"][4:] == ["UAT-JNY-EPIS-07", "UAT-JNY-EPIS-10"]
    assert by_id["SPN-PRD-audit-log"][4:] == []


def test_req_rows_emit_the_prefixed_case_id_not_the_raw_journey_id(
    sample_trace_path, sample_manifest_path
):
    """A reader following a `UAT Test Case ID` reference from the REQ sheet
    must land on a real row on the UAT sheet, which is keyed by the prefixed
    case id — not the raw journey id."""
    reqs, _ = load_trace(sample_trace_path)
    m = Manifest.from_path(sample_manifest_path)
    rows = req_rows(reqs, m)
    by_id = {r[0]: r for r in rows}
    journey_cols = by_id["SPN-PRD-session-management"][4:]
    assert journey_cols == ["UAT-JNY-AUTH-06"]
    assert "JNY-AUTH-06" not in journey_cols


def test_uat_rows_invert_the_mapping(
    sample_trace_path, sample_graph_path, sample_manifest_path
):
    reqs, _ = load_trace(sample_trace_path)
    titles = load_journeys(sample_graph_path)
    m = Manifest.from_path(sample_manifest_path)
    rows = uat_rows(reqs, titles, m)
    by_case = {r[0]: r for r in rows}
    assert by_case["UAT-JNY-EPIS-10"][1] == "Opening a Day From the Calendar"
    assert by_case["UAT-JNY-EPIS-10"][3] == "JNY-EPIS-10"
    assert by_case["UAT-JNY-EPIS-10"][4:] == ["SPN-GUI-calendar-day-view"]


def test_uat_rows_carry_the_journey_verdict(
    sample_trace_path, sample_graph_path, sample_manifest_path
):
    reqs, _ = load_trace(sample_trace_path)
    titles = load_journeys(sample_graph_path)
    m = Manifest.from_path(sample_manifest_path)
    by_case = {r[0]: r for r in uat_rows(reqs, titles, m)}
    assert by_case["UAT-JNY-AUTH-06"][2] == PASS
    assert by_case["UAT-JNY-EPIS-07"][2] == FAIL
    assert by_case["UAT-JNY-EPIS-10"][2] == NOT_RUN


def test_journey_validating_nothing_in_scope_is_absent(
    sample_trace_path, sample_graph_path, sample_manifest_path
):
    reqs, _ = load_trace(sample_trace_path)
    titles = load_journeys(sample_graph_path)
    m = Manifest.from_path(sample_manifest_path)
    assert "UAT-JNY-ORPHAN-01" not in {r[0] for r in uat_rows(reqs, titles, m)}


def test_rows_are_ordered_by_id(sample_trace_path, sample_manifest_path):
    reqs, _ = load_trace(sample_trace_path)
    m = Manifest.from_path(sample_manifest_path)
    ids = [r[0] for r in req_rows(reqs, m)]
    assert ids == sorted(ids)


def test_req_sheet_journey_id_matches_uat_sheet_case_id(
    sample_trace_path, sample_graph_path, sample_manifest_path
):
    """Cross-reference invariant: for a journey validating a requirement, the
    identifier the REQ sheet emits for it must be identical to the identifier
    the UAT sheet emits in its first column for that same journey. A reader
    following a reference from one sheet to the other must land on a real
    row on the other side."""
    reqs, _ = load_trace(sample_trace_path)
    titles = load_journeys(sample_graph_path)
    m = Manifest.from_path(sample_manifest_path)

    req_journey_ids = {
        jid for row in req_rows(reqs, m) for jid in row[4:]
    }
    uat_case_ids = {row[0] for row in uat_rows(reqs, titles, m)}

    assert req_journey_ids
    assert req_journey_ids == uat_case_ids


def test_journey_shared_across_two_reqs_with_same_verdict(sample_manifest_path):
    """A journey validating two requirements with the same verdict appears once
    on the UAT sheet with both requirement ids in its trailing columns."""
    shared_journey = JourneyRef("JNY-SHARED", "pass")
    r1 = _req("REQ-A", 1.0, [shared_journey])
    r2 = _req("REQ-B", 1.0, [shared_journey])
    m = Manifest.from_path(sample_manifest_path)
    rows = uat_rows((r1, r2), {}, m)

    # Should have one row for the shared journey
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == f"{m.uat_case_prefix}JNY-SHARED"
    assert row[2] == PASS
    assert row[3] == "JNY-SHARED"
    # Both requirement ids in trailing columns
    assert row[4:] == ["REQ-A", "REQ-B"]


def test_journey_shared_across_two_reqs_with_conflicting_verdicts(sample_manifest_path):
    """A journey cited by multiple requirements with conflicting verdicts
    raises ValueError naming the journey, both verdicts, and the requirement ids."""
    r1 = _req("REQ-A", 1.0, [JourneyRef("JNY-CONFLICT", "pass")])
    r2 = _req("REQ-B", 1.0, [JourneyRef("JNY-CONFLICT", "fail")])
    m = Manifest.from_path(sample_manifest_path)

    with pytest.raises(ValueError) as exc_info:
        uat_rows((r1, r2), {}, m)

    error = str(exc_info.value)
    assert "JNY-CONFLICT" in error
    assert "pass" in error
    assert "fail" in error
    assert "REQ-A" in error
    assert "REQ-B" in error


def test_journey_shared_across_two_reqs_with_equivalent_pass_verdicts(sample_manifest_path):
    """A journey cited with 'pass' and 'passed' does not raise, since both
    normalize to the same verdict."""
    r1 = _req("REQ-A", 1.0, [JourneyRef("JNY-EQUIV", "pass")])
    r2 = _req("REQ-B", 1.0, [JourneyRef("JNY-EQUIV", "passed")])
    m = Manifest.from_path(sample_manifest_path)

    # Should not raise
    rows = uat_rows((r1, r2), {}, m)

    # Should have one row with PASS verdict
    assert len(rows) == 1
    assert rows[0][2] == PASS
    assert rows[0][4:] == ["REQ-A", "REQ-B"]


# --- test-verification verdict -------------------------------------------
#
# The same asymmetry as the journey rule, on the other kind of evidence:
# a failure outranks everything, a pass demands complete verification, and
# every remaining state -- including a test that exists but has not been run
# -- is an absence, never a failure.


def test_verification_fail_when_a_test_failed():
    r = _req("SPN-PRD-a", 0.0, [], verified_ratio=0.5, tested_failed=2.0)
    assert verification_verdict(r) == FAIL


def test_verification_fail_outranks_full_verification():
    """A requirement can be fully verified and still have a failing test
    citing it; the failure is the reportable fact."""
    r = _req("SPN-PRD-a", 0.0, [], verified_ratio=1.0, tested_failed=1.0)
    assert verification_verdict(r) == FAIL


def test_verification_pass_only_when_fully_verified():
    r = _req("SPN-PRD-a", 0.0, [], verified_ratio=1.0, tested_failed=0.0)
    assert verification_verdict(r) == PASS


def test_verification_partial_is_not_run_not_pass():
    """Partial verification is not a pass: some assertion of this requirement
    has no passing test behind it."""
    r = _req("SPN-PRD-a", 0.0, [], verified_ratio=0.99, tested_failed=0.0)
    assert verification_verdict(r) == NOT_RUN


def test_verification_awaiting_is_not_run_never_fail():
    """Tests exist and cite every assertion, but no result has been ingested:
    `tested.ratio` is 1.0 while `verified.ratio` is 0.0 and nothing failed.
    Reporting that as FAIL would call an un-ingested result a defect."""
    r = _req("SPN-PRD-a", 0.0, [], verified_ratio=0.0, tested_failed=0.0)
    assert verification_verdict(r) == NOT_RUN


def test_verification_no_tests_at_all_is_not_run():
    r = _req("SPN-PRD-a", 0.0, [], verified_ratio=0.0, tested_failed=0.0)
    assert verification_verdict(r) == NOT_RUN


def test_carried_verification_is_marked_on_the_cell():
    """A carried baseline is a weaker claim than a fresh run and must not read
    as an unqualified pass."""
    r = _req("SPN-PRD-a", 0.0, [], verified_ratio=1.0, verified_carried=True)
    assert verification_verdict(r) == PASS
    assert rendered_verification_verdict(r) == f"{PASS}{CARRIED_SUFFIX}"


def test_fresh_verification_carries_no_marker():
    r = _req("SPN-PRD-a", 0.0, [], verified_ratio=1.0, verified_carried=False)
    assert rendered_verification_verdict(r) == PASS
    assert CARRIED_SUFFIX not in rendered_verification_verdict(r)


# --- the widened requirement row -----------------------------------------


def test_req_rows_state_both_verdicts_in_separate_columns(
    sample_trace_path, sample_manifest_path
):
    """The point of the change: the two kinds of evidence disagree per row,
    in both directions, and a reader can see which one is absent or failing.
    A version emitting a single combined verdict, or emitting the same verdict
    twice, fails this."""
    reqs, _ = load_trace(sample_trace_path)
    m = Manifest.from_path(sample_manifest_path)
    by_id = {r[0]: r for r in req_rows(reqs, m)}

    # Fully verified by passing tests, and a passing journey.
    assert by_id["SPN-PRD-session-management"][2:4] == [PASS, PASS]
    # Tests exist for every assertion but no result is ingested (awaiting),
    # while a validating journey failed.
    assert by_id["SPN-GUI-calendar-day-view"][2:4] == [NOT_RUN, FAIL]
    # Tests failed, and no journey validates it at all.
    assert by_id["SPN-PRD-audit-log"][2:4] == [FAIL, NOT_RUN]


def test_req_row_journey_columns_start_after_both_verdicts(
    sample_trace_path, sample_manifest_path
):
    """The journey columns moved right by one. A row still emitting them at
    index 3 would put a case id under the UAT-result header."""
    reqs, _ = load_trace(sample_trace_path)
    m = Manifest.from_path(sample_manifest_path)
    by_id = {r[0]: r for r in req_rows(reqs, m)}
    row = by_id["SPN-GUI-calendar-day-view"]
    assert row[:2] == ["SPN-GUI-calendar-day-view", "Calendar Day View"]
    assert row[4:] == ["UAT-JNY-EPIS-07", "UAT-JNY-EPIS-10"]
    assert not row[3].startswith(m.uat_case_prefix)


def test_uat_rows_are_unchanged_by_the_widened_req_row(
    sample_trace_path, sample_graph_path, sample_manifest_path
):
    """The UAT sheet reports the journey verdict only and keeps its shape."""
    reqs, _ = load_trace(sample_trace_path)
    titles = load_journeys(sample_graph_path)
    m = Manifest.from_path(sample_manifest_path)
    by_case = {r[0]: r for r in uat_rows(reqs, titles, m)}
    assert by_case["UAT-JNY-AUTH-06"][:4] == [
        "UAT-JNY-AUTH-06", "Extending an Idle Session", PASS, "JNY-AUTH-06",
    ]
    assert by_case["UAT-JNY-AUTH-06"][4:] == ["SPN-PRD-session-management"]
