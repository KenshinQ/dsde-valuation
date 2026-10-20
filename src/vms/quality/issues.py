"""Quality issue catalogue and collector (SPEC §6).

Every issue code has a fixed severity, the §6.1 check it belongs to and a fixed message, so the
behaviour of the gate is auditable from this one table.
"""

from __future__ import annotations

from collections import defaultdict
from enum import Enum

from pydantic import BaseModel, ConfigDict


class Severity(str, Enum):
    CRITICAL = "CRITICAL"            # blocks production-mode valuation
    PIT_INCOMPLETE = "PIT_INCOMPLETE"  # historical versions not reconstructible; not a block
    WARNING = "WARNING"
    INFO = "INFO"


C, P, W, I = Severity.CRITICAL, Severity.PIT_INCOMPLETE, Severity.WARNING, Severity.INFO

# code: (severity, check_id, message)
CODES: dict[str, tuple[Severity, str, str]] = {
    "NO_FINANCIAL_DATA": (C, "DATA_AVAILABILITY", "no financial observations known at as_of for this instrument"),
    "NO_MARKET_DATA": (C, "DATA_AVAILABILITY", "no market observation at or before as_of for this instrument"),
    "DUPLICATE_RECORD": (W, "DUPLICATES_CONFLICTS", "exact duplicate records found; one copy kept"),
    "CONFLICTING_VERSIONS": (C, "DUPLICATES_CONFLICTS",
                             "same source/key/published_at carries different values; no resolution rule"),
    "CONFLICTING_SOURCES": (C, "DUPLICATES_CONFLICTS",
                            "different sources report different latest values for the same key"),
    "CONFLICTING_MARKET_OBS": (C, "DUPLICATES_CONFLICTS", "different market observations for the same timestamp"),
    "CONFLICTING_CORPORATE_ACTION": (C, "DUPLICATES_CONFLICTS",
                                     "same action_id announced twice at the same time with different terms"),
    "NON_CANONICAL_FIELD": (W, "FIELD_VOCABULARY", "field_name not in canonical registry; kept, not converted"),
    "STATEMENT_TYPE_MISMATCH": (C, "FIELD_VOCABULARY", "statement_type disagrees with canonical registry"),
    "CURRENCY_NOT_CNY": (C, "UNIT_CURRENCY", "non-CNY amount; FX normalisation to CNY is not implemented"),
    "SUSPECTED_UNIT_MISMATCH": (W, "UNIT_CURRENCY",
                                "value jumps by >= unit_jump_ratio between versions/periods (unit error?)"),
    "POST_AS_OF_EXCLUDED": (I, "POST_AS_OF", "records not yet known at as_of were excluded from the snapshot"),
    "IRREGULAR_PERIOD": (W, "PERIOD_COVERAGE", "period_end is not a calendar quarter end; excluded from conversion"),
    "MISSING_QUARTER": (W, "PERIOD_COVERAGE", "quarter missing between first and last known period"),
    "CUMULATIVE_CONVENTION_UNKNOWN": (W, "CUMULATIVE_CONVERSION",
                                      "flow reporting convention not declared; flows kept as reported, not converted"),
    "CUMULATIVE_PRIOR_MISSING": (W, "CUMULATIVE_CONVERSION",
                                 "standalone quarter not derivable (prior cumulative missing/null); marked missing"),
    "CUMULATIVE_DERIVED": (I, "CUMULATIVE_CONVERSION", "standalone-quarter flows derived from cumulative YTD"),
    "BALANCE_SHEET_IDENTITY_FAIL": (W, "BALANCE_SHEET_IDENTITY",
                                    "total_assets != total_liabilities + total_equity beyond tolerance"),
    "BALANCE_SHEET_IDENTITY_UNCHECKED": (I, "BALANCE_SHEET_IDENTITY",
                                         "identity not checkable: required fields absent for period"),
    "SIGN_CONVENTION_VIOLATION": (C, "CASH_FLOW_SIGN_UNIT",
                                  "negative value in a positive_magnitude/nonnegative field (registry FIELDS-1)"),
    "CAPEX_REVENUE_IMPLAUSIBLE": (W, "CASH_FLOW_SIGN_UNIT", "capex/revenue exceeds max_capex_to_revenue (unit?)"),
    "UNEXPLAINED_SHARE_CHANGE": (W, "SHARE_COUNT_CORPORATE_ACTIONS",
                                 "shares_outstanding change not explained by known corporate actions"),
    "CORPORATE_ACTIONS_UNAVAILABLE": (W, "SHARE_COUNT_CORPORATE_ACTIONS",
                                      "no corporate_actions table provided; share/price checks are limited"),
    "VENDOR_ADJ_FACTOR_UNEXPLAINED": (W, "PRICE_ADJUSTMENT",
                                      "vendor adjusted/raw factor changes where no known corporate action explains it"),
    "VENDOR_ADJUSTED_CLOSE_EXCLUDED": (I, "PRICE_ADJUSTMENT",
                                       "vendor adjusted_close excluded (may embed post-as_of actions); "
                                       "pit_adjusted_close recomputed from known actions"),
    "SOURCE_UNDECLARED": (P, "PIT_VERSIONING", "source not declared in sources.yaml; versioning unknown"),
    "SOURCE_NOT_FULL_HISTORY": (P, "PIT_VERSIONING", "source does not preserve full version history"),
    "RESTATEMENT_KNOWN": (I, "RESTATEMENTS", "keys with more than one published version known at as_of"),
    "STALE_FINANCIALS": (W, "PERIOD_COVERAGE",
                         "a period required by CN statutory deadlines (STALENESS-CN-DEADLINE-v1) is not known at as_of"),
    "LATE_PUBLICATION": (I, "PERIOD_COVERAGE", "published later than late_publication_days after period_end"),
    "EXPLICIT_MISSING_VALUE": (I, "PROVENANCE", "values explicitly recorded as missing/not_applicable (kept null)"),
    "PROVENANCE_INCOMPLETE": (C, "PROVENANCE", "derived value lacks formula/inputs (internal invariant)"),
}

MAX_EXAMPLES = 25


class QualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: Severity
    check: str
    message: str
    count: int
    examples: list[str]


class IssueCollector:
    def __init__(self) -> None:
        self._ex: dict[str, list[str]] = defaultdict(list)

    def add(self, code: str, example: str) -> None:
        if code not in CODES:
            raise KeyError(f"unknown issue code {code}")
        self._ex[code].append(example)

    def extend(self, other: "IssueCollector") -> None:
        for k, v in other._ex.items():
            self._ex[k].extend(v)

    def issues(self) -> list[QualityIssue]:
        out = []
        for code in sorted(self._ex):
            sev, check, msg = CODES[code]
            ex = sorted(set(self._ex[code]))
            out.append(QualityIssue(code=code, severity=sev, check=check, message=msg,
                                    count=len(self._ex[code]), examples=ex[:MAX_EXAMPLES]))
        return out
