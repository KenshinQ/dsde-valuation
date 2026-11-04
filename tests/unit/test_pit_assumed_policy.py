"""PIT_ASSUMED / VENDOR_LATEST_AS_OF research scoring policy."""

from __future__ import annotations

from vms.pit.policy import (
    VENDOR_LATEST_AS_OF,
    PitPolicy,
    classify_pit_policy,
    research_score_eligible,
    vendor_latest_as_of,
)
from vms.schemas.observations import ReportingConvention, SourceDescriptor, Versioning


def _sd(versioning: str, sid: str = "S") -> SourceDescriptor:
    return SourceDescriptor(
        source_id=sid,
        reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
        versioning=versioning,
    )


def test_classify_full_history_is_complete():
    assert classify_pit_policy({"S": _sd("FULL_HISTORY")}) is PitPolicy.PIT_COMPLETE


def test_classify_latest_only_is_assumed_not_complete():
    pol = classify_pit_policy({"S": _sd("LATEST_ONLY")})
    assert pol is PitPolicy.PIT_ASSUMED
    assert vendor_latest_as_of(pol) is True
    assert VENDOR_LATEST_AS_OF == "VENDOR_LATEST_AS_OF"


def test_classify_undeclared_is_incomplete():
    assert classify_pit_policy({"S": None}) is PitPolicy.PIT_INCOMPLETE


def test_classify_unknown_versioning_is_incomplete():
    assert classify_pit_policy({"S": _sd("UNKNOWN")}) is PitPolicy.PIT_INCOMPLETE


def test_classify_empty_sources_vacuous_complete():
    assert classify_pit_policy({}) is PitPolicy.PIT_COMPLETE
    assert classify_pit_policy(None) is PitPolicy.PIT_COMPLETE


def test_classify_mixed_full_and_latest_is_assumed():
    sources = {
        "A": _sd("FULL_HISTORY", "A"),
        "B": _sd("LATEST_ONLY", "B"),
    }
    assert classify_pit_policy(sources) is PitPolicy.PIT_ASSUMED


def test_research_eligible_complete_or_assumed_only():
    assert research_score_eligible({"pit_complete": True, "pit_policy": "PIT_COMPLETE"})
    assert research_score_eligible({"pit_complete": False, "pit_policy": "PIT_ASSUMED"})
    assert not research_score_eligible({"pit_complete": False, "pit_policy": "PIT_INCOMPLETE"})
    assert not research_score_eligible({"pit_complete": False, "pit_policy": None})


def test_research_filter_includes_assumed_excludes_incomplete():
    scored = [
        {"instrument_id": "A", "pit_complete": True, "pit_policy": "PIT_COMPLETE"},
        {"instrument_id": "B", "pit_complete": False, "pit_policy": "PIT_ASSUMED"},
        {"instrument_id": "C", "pit_complete": False, "pit_policy": "PIT_INCOMPLETE"},
    ]
    eligible = [r for r in scored if research_score_eligible(r)]
    assert {r["instrument_id"] for r in eligible} == {"A", "B"}
    strict = [r for r in scored if r.get("pit_complete")]
    assert {r["instrument_id"] for r in strict} == {"A"}
