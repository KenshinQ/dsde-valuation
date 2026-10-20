"""Versioned capital-allocation policies (SPEC §10). Management is not assumed to be optimal.

Every policy returns explicit decisions with formulas/inputs for the ledger. Shared mechanics
(revolver to the min-cash floor, buyback/issuance pricing) live in the projection and are
labeled by assumption IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vms.schemas.config import CapitalAllocationConfig


@dataclass(frozen=True)
class Decision:
    value: float
    formula: str
    inputs: list[str]


@dataclass(frozen=True)
class AllocationState:
    year: int
    revenue: float
    parent_net_income: float
    ebitda: float
    cash_before_distributions: float
    debt_open: float


class Policy:
    policy_id: str = ""
    version: str = "1"

    def __init__(self, params: dict[str, Any], drivers: dict[str, float]) -> None:
        self.params = params
        self.d = drivers

    # -- hooks (defaults = conservative choices)
    def acquisitions(self, revenue: float, y: int) -> Decision:
        return Decision(0.0, "0 (policy: no acquisitions)", [])

    def dividends(self, s: AllocationState) -> Decision:
        return Decision(self.d["payout_ratio"] * max(s.parent_net_income, 0.0),
                        "payout_ratio x max(parent_net_income, 0)",
                        ["driver:payout_ratio", f"parent_net_income@{s.year}"])

    def repurchases(self, s: AllocationState) -> Decision:
        return Decision(0.0, "0 (policy: no buybacks)", [])

    def issuance_cash(self, s: AllocationState) -> Decision:
        return Decision(0.0, "0 (policy: no cash equity issuance)", [])

    def debt_target(self, s: AllocationState) -> Decision:
        return Decision(s.debt_open, "debt held flat (refinanced)", [f"interest_bearing_debt@{s.year - 1}"])

    def describe(self) -> dict[str, Any]:
        return {"policy_id": self.policy_id, "version": self.version, "params": self.params}


class ConservativeBaseline(Policy):
    policy_id = "conservative_baseline"


class HistoricalContinuation(Policy):
    policy_id = "historical_continuation"

    def acquisitions(self, revenue: float, y: int) -> Decision:
        return Decision(self.d["acquisitions_to_revenue"] * revenue, "acquisitions_to_revenue x revenue",
                        ["driver:acquisitions_to_revenue", f"revenue@{y}"])

    def repurchases(self, s: AllocationState) -> Decision:
        return Decision(self.d["repurchases_to_net_income"] * max(s.parent_net_income, 0.0),
                        "repurchases_to_net_income x max(parent_net_income, 0)",
                        ["driver:repurchases_to_net_income", f"parent_net_income@{s.year}"])

    def debt_target(self, s: AllocationState) -> Decision:
        return Decision(self.d["debt_to_revenue"] * s.revenue, "debt_to_revenue x revenue",
                        ["driver:debt_to_revenue", f"revenue@{s.year}"])


class FixedPayout(Policy):
    policy_id = "fixed_payout"

    def dividends(self, s: AllocationState) -> Decision:
        return Decision(self.params["payout_ratio"] * max(s.parent_net_income, 0.0),
                        "policy.payout_ratio x max(parent_net_income, 0)",
                        ["policy:payout_ratio", f"parent_net_income@{s.year}"])


class TargetLeverage(Policy):
    policy_id = "target_leverage"

    def debt_target(self, s: AllocationState) -> Decision:
        lo, hi = self.params["debt_to_ebitda_min"], self.params["debt_to_ebitda_max"]
        refs = ["policy:debt_to_ebitda_min", "policy:debt_to_ebitda_max", f"ebitda@{s.year}",
                f"interest_bearing_debt@{s.year - 1}"]
        if s.ebitda <= 0:
            return Decision(s.debt_open, "EBITDA <= 0: debt held flat (target undefined)", refs)
        return Decision(min(max(s.debt_open, lo * s.ebitda), hi * s.ebitda),
                        "clip(opening debt, min x EBITDA, max x EBITDA)", refs)


class MinCashExcessDistribution(Policy):
    policy_id = "min_cash_excess_distribution"

    def _excess(self, s: AllocationState) -> float:
        return max(s.cash_before_distributions - self.params["min_cash_to_revenue"] * s.revenue, 0.0)

    def dividends(self, s: AllocationState) -> Decision:
        return Decision(self._excess(s) * self.params["dividend_share"],
                        "max(cash_before_distributions - min_cash_to_revenue x revenue, 0) x dividend_share",
                        ["policy:min_cash_to_revenue", "policy:dividend_share", f"revenue@{s.year}",
                         f"cash_before_distributions@{s.year}"])

    def repurchases(self, s: AllocationState) -> Decision:
        return Decision(self._excess(s) * (1 - self.params["dividend_share"]),
                        "max(cash_before_distributions - min_cash_to_revenue x revenue, 0) x (1 - dividend_share)",
                        ["policy:min_cash_to_revenue", "policy:dividend_share", f"revenue@{s.year}",
                         f"cash_before_distributions@{s.year}"])


POLICIES: dict[str, type[Policy]] = {p.policy_id: p for p in
                                     (ConservativeBaseline, HistoricalContinuation, FixedPayout, TargetLeverage,
                                      MinCashExcessDistribution)}


def make_policy(policy_id: str, cfg: CapitalAllocationConfig, drivers: dict[str, float]) -> Policy:
    if policy_id not in POLICIES:
        raise ValueError(f"unknown capital-allocation policy {policy_id!r}; known: {sorted(POLICIES)}")
    params = getattr(cfg.policies, policy_id).model_dump()
    cls = POLICIES[policy_id]
    if params.get("version") != cls.version:
        raise ValueError(f"policy {policy_id}: config version {params.get('version')} != implemented {cls.version}")
    return cls(params, drivers)
