"""Apply a peer multiple to subject fundamentals with bridge discipline (SPEC §12.5/§12.8).

Equity methods (P/E, P/B): never EV-bridge.
EV methods: EV = multiple × denom, then bridge_ev_to_equity exactly once.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.equity_bridge.bridge import BridgeResult, bridge_ev_to_equity
from vms.methods.multiples.definitions import MetricDefinition, ValueClaimKind


class MultipleValueResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    invalid_reason: str | None = None
    method_id: str
    multiple_used: float | None
    denominator_field: str
    denominator_value: float | None
    claim_object: str
    value_claim: str
    enterprise_value: float | None = None
    equity_value: float | None = None
    value_per_share: float | None = None
    diluted_shares: float | None = None
    ev_bridge_applied: bool = False
    bridge: dict[str, Any] | None = None
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    formula: str = ""


def apply_equity_multiple(
    *,
    definition: MetricDefinition,
    multiple: float,
    denominator: float,
    diluted_shares: float | None,
) -> MultipleValueResult:
    assumptions = cite("PEER-MULTIPLE-RELATIVE-v1", "NO-DOUBLE-EV-BRIDGE-v1")
    flags: list[str] = []
    if definition.applies_ev_bridge:
        return MultipleValueResult(
            valid=False, invalid_reason="BRIDGE_CONTRACT_MISMATCH",
            method_id=definition.method_id, multiple_used=multiple,
            denominator_field=definition.denominator_field, denominator_value=denominator,
            claim_object=definition.claim_object.value, value_claim=definition.value_claim.value,
            flags=["EXPECTED_EQUITY_METHOD"], assumptions=assumptions, formula=definition.formula,
        )
    if not (math.isfinite(multiple) and multiple > 0 and math.isfinite(denominator)):
        return MultipleValueResult(
            valid=False, invalid_reason="NONFINITE_INPUTS",
            method_id=definition.method_id, multiple_used=multiple,
            denominator_field=definition.denominator_field, denominator_value=denominator,
            claim_object=definition.claim_object.value, value_claim=definition.value_claim.value,
            assumptions=assumptions, formula=definition.formula,
        )
    equity = multiple * denominator
    vps = None
    shares = diluted_shares
    if shares is None or not math.isfinite(shares) or shares <= 0:
        flags.append("MISSING_OR_NONPOSITIVE_SHARES")
    else:
        vps = equity / shares
    if definition.value_claim is ValueClaimKind.RELATIVE_PRICING_ONLY:
        flags.append("RELATIVE_PRICING_NOT_INTRINSIC")
    return MultipleValueResult(
        valid=True, method_id=definition.method_id, multiple_used=multiple,
        denominator_field=definition.denominator_field, denominator_value=denominator,
        claim_object=definition.claim_object.value, value_claim=definition.value_claim.value,
        enterprise_value=None, equity_value=equity, value_per_share=vps,
        diluted_shares=shares, ev_bridge_applied=False, bridge=None,
        flags=sorted(flags), assumptions=assumptions, formula=definition.formula,
    )


def apply_ev_multiple(
    *,
    definition: MetricDefinition,
    multiple: float,
    denominator: float,
    cash: float,
    debt: float,
    lease_debt_like: float = 0.0,
    minority_interest_book: float = 0.0,
    other_senior_claims: float = 0.0,
    diluted_shares: float,
) -> MultipleValueResult:
    assumptions = cite("PEER-MULTIPLE-RELATIVE-v1", "EV-EQUITY-BRIDGE-v1", "NO-DOUBLE-EV-BRIDGE-v1")
    flags: list[str] = []
    if not definition.applies_ev_bridge:
        return MultipleValueResult(
            valid=False, invalid_reason="BRIDGE_CONTRACT_MISMATCH",
            method_id=definition.method_id, multiple_used=multiple,
            denominator_field=definition.denominator_field, denominator_value=denominator,
            claim_object=definition.claim_object.value, value_claim=definition.value_claim.value,
            flags=["EXPECTED_EV_METHOD"], assumptions=assumptions, formula=definition.formula,
        )
    if not (math.isfinite(multiple) and multiple > 0 and math.isfinite(denominator)):
        return MultipleValueResult(
            valid=False, invalid_reason="NONFINITE_INPUTS",
            method_id=definition.method_id, multiple_used=multiple,
            denominator_field=definition.denominator_field, denominator_value=denominator,
            claim_object=definition.claim_object.value, value_claim=definition.value_claim.value,
            assumptions=assumptions, formula=definition.formula,
        )
    ev = multiple * denominator
    br: BridgeResult = bridge_ev_to_equity(
        enterprise_value=ev, cash=cash, debt=debt, lease_debt_like=lease_debt_like,
        minority_interest_book=minority_interest_book, other_senior_claims=other_senior_claims,
        diluted_shares=diluted_shares,
    )
    if not br.valid:
        return MultipleValueResult(
            valid=False, invalid_reason=br.invalid_reason,
            method_id=definition.method_id, multiple_used=multiple,
            denominator_field=definition.denominator_field, denominator_value=denominator,
            claim_object=definition.claim_object.value, value_claim=definition.value_claim.value,
            enterprise_value=ev, equity_value=None, value_per_share=None,
            diluted_shares=diluted_shares, ev_bridge_applied=True,
            bridge=br.model_dump(mode="json"), flags=sorted(br.flags + flags),
            assumptions=assumptions, formula=definition.formula,
        )
    if definition.value_claim is ValueClaimKind.RELATIVE_PRICING_ONLY:
        flags.append("RELATIVE_PRICING_NOT_INTRINSIC")
    flags.extend(br.flags)
    return MultipleValueResult(
        valid=True, method_id=definition.method_id, multiple_used=multiple,
        denominator_field=definition.denominator_field, denominator_value=denominator,
        claim_object=definition.claim_object.value, value_claim=definition.value_claim.value,
        enterprise_value=ev, equity_value=br.equity_value, value_per_share=br.value_per_share,
        diluted_shares=diluted_shares, ev_bridge_applied=True,
        bridge=br.model_dump(mode="json"), flags=sorted(set(flags)),
        assumptions=assumptions, formula=definition.formula,
    )
