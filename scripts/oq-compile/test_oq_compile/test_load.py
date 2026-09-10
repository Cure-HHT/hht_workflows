from __future__ import annotations

import json

from oq_compile.load import load_journeys, load_trace


def test_loads_requirements(sample_trace_path):
    reqs, _ = load_trace(sample_trace_path)
    assert len(reqs) == 3
    assert reqs[0].id == "SPN-PRD-session-management"
    assert reqs[0].level == "PRD"
    assert reqs[0].status == "Active"
    assert reqs[0].uat_verified_ratio == 1.0


def test_deduplicates_repeated_journeys(sample_trace_path):
    reqs, _ = load_trace(sample_trace_path)
    calendar = next(r for r in reqs if r.id == "SPN-GUI-calendar-day-view")
    assert [j.id for j in calendar.journeys] == ["JNY-EPIS-10", "JNY-EPIS-07"]


def test_preserves_verdicts(sample_trace_path):
    reqs, _ = load_trace(sample_trace_path)
    calendar = next(r for r in reqs if r.id == "SPN-GUI-calendar-day-view")
    assert calendar.journeys[0].verdict == "unverified"
    assert calendar.journeys[1].verdict == "fail"


def test_requirement_with_no_journeys(sample_trace_path):
    reqs, _ = load_trace(sample_trace_path)
    audit = next(r for r in reqs if r.id == "SPN-PRD-audit-log")
    assert audit.journeys == ()


def test_bare_list_has_no_scope_header(sample_trace_path):
    _, scope = load_trace(sample_trace_path)
    assert scope == ()


def test_accepts_dict_form_with_scope_header(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            {
                "scope": ["Scope: level PRD or GUI", "Scope selected 2 of 9"],
                "requirements": [
                    {
                        "id": "SPN-PRD-a",
                        "title": "A",
                        "level": "PRD",
                        "status": "Draft",
                        "uat_verified": {"ratio": 0.0},
                        "journeys": [],
                    }
                ],
            }
        )
    )
    reqs, scope = load_trace(p)
    assert len(reqs) == 1
    assert scope[0].startswith("Scope: level")


def test_loads_journey_titles(sample_graph_path):
    titles = load_journeys(sample_graph_path)
    assert len(titles) == 4
    assert titles["JNY-AUTH-06"] == "Extending an Idle Session"
    assert titles["JNY-EPIS-10"] == "Opening a Day From the Calendar"
    assert titles["JNY-EPIS-07"] == "Duration Reasonableness Check on Save"
    assert titles["JNY-ORPHAN-01"] == "Validates Nothing In Scope"
    assert "SPN-PRD-session-management" not in titles


def test_missing_requirement_id_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            [
                {
                    "title": "A",
                    "level": "PRD",
                    "status": "Draft",
                    "uat_verified": {"ratio": 0.0},
                    "journeys": [],
                }
            ]
        )
    )
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "requirement row 0" in str(e)
        assert "id" in str(e)


def test_missing_uat_verified_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": "SPN-PRD-a",
                    "title": "A",
                    "level": "PRD",
                    "status": "Draft",
                    "journeys": [],
                }
            ]
        )
    )
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "requirement row 0" in str(e)
        assert "uat_verified" in str(e)


def test_missing_uat_verified_ratio_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": "SPN-PRD-a",
                    "title": "A",
                    "level": "PRD",
                    "status": "Draft",
                    "uat_verified": {},
                    "journeys": [],
                }
            ]
        )
    )
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "requirement row 0" in str(e)
        assert "ratio" in str(e)


def test_missing_journey_id_fails_loud(tmp_path):
    p = tmp_path / "trace.json"
    p.write_text(
        json.dumps(
            [
                {
                    "id": "SPN-PRD-a",
                    "title": "A",
                    "level": "PRD",
                    "status": "Draft",
                    "uat_verified": {"ratio": 0.0},
                    "journeys": [{"verdict": "pass"}],
                }
            ]
        )
    )
    try:
        load_trace(p)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "journey entry 0" in str(e)
        assert "id" in str(e)
