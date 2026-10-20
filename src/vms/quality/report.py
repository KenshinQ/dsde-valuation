"""Data-quality report and production gate (SPEC §6.2)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms.data.io import LoadResult
from vms.pit.snapshot import BuildStats, PITSnapshot, build_snapshot
from vms.quality.checks import CHECK_CATALOGUE, run_checks
from vms.quality.issues import IssueCollector, QualityIssue, Severity
from vms.schemas.config import QualityConfig

REPORT_VERSION = "DQ-REPORT-1"


class QualityState(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    BLOCKED = "BLOCKED"
    PIT_INCOMPLETE = "PIT_INCOMPLETE"


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    check: str
    status: Literal["RUN", "DEFERRED"]
    spec_ref: str
    issue_count: int


class Override(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["exploratory"]
    reason: str = Field(min_length=3)
    overridden_critical_codes: list[str]


class DataQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: str = REPORT_VERSION
    instrument_id: str
    as_of: datetime
    mode: Literal["production", "exploratory"]
    status: QualityState
    pit_complete: bool
    usable_for_production: bool
    checks: list[CheckResult]
    issues: list[QualityIssue]
    severity_counts: dict[str, int]
    excluded_post_as_of: dict[str, int]
    override: Override | None = None

    @model_validator(mode="after")
    def _override_consistency(self) -> "DataQualityReport":
        if self.override is not None and self.mode != "exploratory":
            raise ValueError("override recorded but mode is not exploratory")
        return self


def status_of(issues: list[QualityIssue]) -> QualityState:
    sev = {i.severity for i in issues}
    if Severity.CRITICAL in sev:
        return QualityState.BLOCKED
    if Severity.PIT_INCOMPLETE in sev:
        return QualityState.PIT_INCOMPLETE
    if Severity.WARNING in sev:
        return QualityState.PASS_WITH_WARNINGS
    return QualityState.PASS


class GateError(RuntimeError):
    """Production-mode valuation blocked by critical data-quality errors."""


def assess(load: LoadResult, *, instrument_id: str, as_of: datetime, cfg: QualityConfig,
           mode: Literal["production", "exploratory"] = "production",
           override_reason: str | None = None) -> tuple[PITSnapshot, DataQualityReport]:
    """Build the PIT snapshot and its quality report. Never raises on data problems; see ``gate``."""
    if mode == "exploratory" and not (override_reason and override_reason.strip()):
        raise ValueError("exploratory mode requires an explicit override reason (--override-reason)")
    snap, stats, ic = build_snapshot(instrument_id=instrument_id, as_of=as_of, financial=load.financial,
                                     market=load.market, corporate_actions=load.corporate_actions,
                                     sources=load.sources, classifications=load.classifications)
    known_market = [m for m in load.market if m.instrument_id == instrument_id and m.timestamp <= as_of]
    known_actions = [e for e in load.corporate_actions if e.instrument_id == instrument_id and e.announced_at <= as_of]
    checks_ic = IssueCollector()
    run_checks(snap, known_market=known_market, known_actions=known_actions,
               corporate_actions_provided=load.corporate_actions_provided, cfg=cfg, ic=checks_ic)
    ic.extend(checks_ic)
    for table, n in stats.excluded_post_as_of.items():
        for _ in range(n):
            ic.add("POST_AS_OF_EXCLUDED", table)
    issues = ic.issues()
    status = status_of(issues)
    counts = {s.value: sum(i.count for i in issues if i.severity is s) for s in Severity}
    checks = [CheckResult(check=c, status=st, spec_ref=ref,
                          issue_count=sum(i.count for i in issues if i.check == c))
              for c, (st, ref) in CHECK_CATALOGUE.items()]
    critical = sorted({i.code for i in issues if i.severity is Severity.CRITICAL})
    override = None
    if mode == "exploratory":
        override = Override(mode="exploratory", reason=override_reason.strip(), overridden_critical_codes=critical)
    report = DataQualityReport(
        instrument_id=instrument_id, as_of=as_of, mode=mode, status=status,
        pit_complete=not any(i.severity is Severity.PIT_INCOMPLETE for i in issues),
        usable_for_production=status is not QualityState.BLOCKED,
        checks=checks, issues=issues, severity_counts=counts,
        excluded_post_as_of=stats.excluded_post_as_of, override=override)
    return snap, report


def gate(report: DataQualityReport) -> None:
    """Raise GateError if production-mode use must be blocked."""
    if report.status is QualityState.BLOCKED and report.mode == "production":
        codes = sorted({i.code for i in report.issues if i.severity is Severity.CRITICAL})
        raise GateError(f"{report.instrument_id} as_of {report.as_of.isoformat()}: BLOCKED by critical "
                        f"data-quality errors {codes}. Fix the data, or rerun with --mode exploratory "
                        f"--override-reason '...' (recorded in the report; not production-usable).")
