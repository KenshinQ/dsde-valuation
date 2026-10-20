"""EV → equity bridge (SPEC §11.4). EV-EQUITY-BRIDGE-v1."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite


class BridgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valid: bool
    invalid_reason: str | None = None
    enterprise_value: float
    cash: float
    debt: float
    lease_debt_like: float
    minority_interest_book: float
    other_senior_claims: float
    equity_value: float | None
    diluted_shares: float
    value_per_share: float | None
    components: dict[str, float]
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def bridge_ev_to_equity(*, enterprise_value: float, cash: float, debt: float, lease_debt_like: float,
                        minority_interest_book: float, other_senior_claims: float,
                        diluted_shares: float) -> BridgeResult:
    assumptions = cite("EV-EQUITY-BRIDGE-v1", "LEASE-BRIDGE-DEBTLIKE-v1", "MINORITY-BOOK-BRIDGE-v1")
    flags: list[str] = []
    comps = {
        "enterprise_value": enterprise_value,
        "cash_and_non_operating": cash,          # +
        "interest_bearing_debt": -debt,          # −
        "lease_debt_like": -lease_debt_like,     # −
        "minority_interest_book": -minority_interest_book,
        "other_senior_claims": -other_senior_claims,
    }
    if diluted_shares <= 0 or not math.isfinite(diluted_shares):
        return BridgeResult(valid=False, invalid_reason="NONPOSITIVE_SHARES", enterprise_value=enterprise_value,
                            cash=cash, debt=debt, lease_debt_like=lease_debt_like,
                            minority_interest_book=minority_interest_book,
                            other_senior_claims=other_senior_claims, equity_value=None,
                            diluted_shares=diluted_shares, value_per_share=None, components=comps,
                            flags=flags, assumptions=assumptions)
    eq = (enterprise_value + cash - debt - lease_debt_like - minority_interest_book - other_senior_claims)
    if not math.isfinite(eq):
        return BridgeResult(valid=False, invalid_reason="BRIDGE_NONFINITE", enterprise_value=enterprise_value,
                            cash=cash, debt=debt, lease_debt_like=lease_debt_like,
                            minority_interest_book=minority_interest_book,
                            other_senior_claims=other_senior_claims, equity_value=None,
                            diluted_shares=diluted_shares, value_per_share=None, components=comps,
                            flags=flags, assumptions=assumptions)
    if eq < 0:
        flags.append("NEGATIVE_EQUITY_PRESERVED")  # no silent clamp
    vps = eq / diluted_shares
    return BridgeResult(valid=True, enterprise_value=enterprise_value, cash=cash, debt=debt,
                        lease_debt_like=lease_debt_like, minority_interest_book=minority_interest_book,
                        other_senior_claims=other_senior_claims, equity_value=eq,
                        diluted_shares=diluted_shares, value_per_share=vps, components=comps,
                        flags=sorted(flags), assumptions=assumptions)
