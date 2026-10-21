"""Explicit multiple metric definitions (SPEC §12.5 / §10.2).

Each metric declares: denominator field, output claim object, whether an EV→equity
bridge is applied exactly once, and intrinsic vs relative-pricing labeling.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimObject(str, Enum):
    """What the multiple estimates before any optional bridge."""

    EQUITY = "EQUITY"
    EV = "EV"


class ValueClaimKind(str, Enum):
    """SPEC §12.5: EV/Sales (and growth/neg-earnings cases) may be relative pricing only."""

    RELATIVE_EQUITY = "RELATIVE_EQUITY"
    RELATIVE_EV = "RELATIVE_EV"
    RELATIVE_PRICING_ONLY = "RELATIVE_PRICING_ONLY"  # not an intrinsic-value claim


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    display_name: str
    peer_field_name: str = Field(description="PeerObservation.field_name for this multiple")
    denominator_field: str = Field(description="Subject fundamental used as denominator")
    claim_object: ClaimObject
    value_claim: ValueClaimKind
    applies_ev_bridge: bool
    formula: str
    notes: str = ""


# Canonical Phase-5 definitions — single source of truth for plugins and tests.
METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "pe": MetricDefinition(
        method_id="pe",
        display_name="P/E multiple",
        peer_field_name="pe",
        denominator_field="parent_net_income",
        claim_object=ClaimObject.EQUITY,
        value_claim=ValueClaimKind.RELATIVE_EQUITY,
        applies_ev_bridge=False,
        formula="EquityValue = peer_multiple × parent_net_income; ValuePerShare = EquityValue / diluted_shares",
        notes="Equity-side only; never apply EV→equity bridge (SPEC §12.8).",
    ),
    "pb": MetricDefinition(
        method_id="pb",
        display_name="P/B multiple",
        peer_field_name="pb",
        denominator_field="total_equity",
        claim_object=ClaimObject.EQUITY,
        value_claim=ValueClaimKind.RELATIVE_EQUITY,
        applies_ev_bridge=False,
        formula="EquityValue = peer_multiple × total_equity (book); ValuePerShare = EquityValue / diluted_shares",
        notes="Equity-side only; never apply EV→equity bridge (SPEC §12.8).",
    ),
    "ev_ebit": MetricDefinition(
        method_id="ev_ebit",
        display_name="EV/EBIT multiple",
        peer_field_name="ev_ebit",
        denominator_field="ebit",
        claim_object=ClaimObject.EV,
        value_claim=ValueClaimKind.RELATIVE_EV,
        applies_ev_bridge=True,
        formula="EV = peer_multiple × ebit; EquityValue = EV + cash − debt − leases − minority − other (once)",
        notes="EV first, then single EV→equity bridge.",
    ),
    "ev_ebitda": MetricDefinition(
        method_id="ev_ebitda",
        display_name="EV/EBITDA multiple",
        peer_field_name="ev_ebitda",
        denominator_field="ebitda",
        claim_object=ClaimObject.EV,
        value_claim=ValueClaimKind.RELATIVE_EV,
        applies_ev_bridge=True,
        formula="EV = peer_multiple × ebitda; EquityValue = bridge(EV) once",
        notes="EBITDA is not cash flow; bridge once only.",
    ),
    "ev_sales": MetricDefinition(
        method_id="ev_sales",
        display_name="EV/Sales multiple",
        peer_field_name="ev_sales",
        denominator_field="revenue",
        claim_object=ClaimObject.EV,
        value_claim=ValueClaimKind.RELATIVE_PRICING_ONLY,
        applies_ev_bridge=True,
        formula="EV = peer_multiple × revenue; EquityValue = bridge(EV) once",
        notes="Labeled relative pricing, not economic intrinsic value, unless implied margins modeled.",
    ),
}


AggregatorName = Literal["median", "winsorized_mean", "trimmed_mean"]


def get_definition(method_id: str) -> MetricDefinition:
    if method_id not in METRIC_DEFINITIONS:
        raise KeyError(f"unknown multiple method_id={method_id!r}")
    return METRIC_DEFINITIONS[method_id]
