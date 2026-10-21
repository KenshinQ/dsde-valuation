"""Sum-of-the-parts framework (SPEC §12.7).

SOTP must split materially different businesses, assign each segment a value
(eligible method or configured), eliminate inter-segment items, and account for
group costs, parent debt, minorities and non-operating assets. Holding-company
discount/premium is an explicit uncertain parameter — never an undisclosed plug.
Missing segment inputs ⇒ data-gap / unsupported.
"""

from __future__ import annotations

import math
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms.assumptions import cite

INVALID_SOTP_REASONS = (
    "MISSING_SEGMENT_INPUTS",
    "INTER_SEGMENT_UNRECONCILED",
    "NONFINITE_SOTP",
    "EMPTY_SEGMENT_SCHEDULE",
    "HOLDING_DISCOUNT_UNDECLARED_PLUG",
)


class SegmentLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segment_id: str = Field(min_length=1)
    equity_value: float | None = None
    ev_value: float | None = None
    method: str = Field(default="configured", description="configured | fcff_dcf | pe | nav | ...")
    inter_segment_receivable: float = 0.0
    inter_segment_payable: float = 0.0
    notes: str = ""

    @model_validator(mode="after")
    def _need_value(self) -> "SegmentLine":
        if self.equity_value is None and self.ev_value is None:
            raise ValueError(f"segment {self.segment_id}: equity_value or ev_value required")
        for name in ("equity_value", "ev_value", "inter_segment_receivable", "inter_segment_payable"):
            v = getattr(self, name)
            if v is not None and not math.isfinite(float(v)):
                raise ValueError(f"{name} must be finite")
        return self


class HoldingDiscount(BaseModel):
    """Explicit uncertain holding discount/premium (fraction of gross SOTP equity)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rate: float = Field(ge=-0.5, le=0.9, description="positive = discount; negative = premium")
    uncertain: bool = True
    low: float | None = None
    high: float | None = None
    rationale: str = Field(min_length=1)


class SotpResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    invalid_reason: str | None = None
    unsupported: bool = False
    data_gap: list[str] = Field(default_factory=list)
    equity_value: float | None = None
    gross_segment_equity: float | None = None
    reconciliation: dict[str, Any] = Field(default_factory=dict)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    holding_discount: dict[str, Any] | None = None
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    detail: str = ""


def compute_sotp(
    *,
    segments: Sequence[SegmentLine | dict[str, Any]],
    inter_segment_elimination: float | None = None,
    group_costs_pv: float = 0.0,
    parent_debt: float = 0.0,
    minority_interest: float = 0.0,
    non_operating_assets: float = 0.0,
    holding_discount: HoldingDiscount | dict[str, Any] | None = None,
    require_holding_discount_declared: bool = False,
    diluted_shares: float | None = None,
) -> SotpResult:
    assumptions = cite("SOTP-RECONCILE-v1", "SOTP-HOLDING-DISCOUNT-EXPLICIT-v1")
    flags: list[str] = []
    if not segments:
        return SotpResult(
            valid=False,
            invalid_reason="EMPTY_SEGMENT_SCHEDULE",
            unsupported=True,
            data_gap=["segments"],
            assumptions=assumptions,
            detail="SOTP requires a non-empty segment schedule",
        )

    seg_models: list[SegmentLine] = []
    for s in segments:
        try:
            seg_models.append(s if isinstance(s, SegmentLine) else SegmentLine(**s))
        except Exception as e:  # noqa: BLE001 — surface as data-gap
            return SotpResult(
                valid=False,
                invalid_reason="MISSING_SEGMENT_INPUTS",
                unsupported=True,
                data_gap=[f"segment_parse:{e}"],
                assumptions=assumptions,
                detail=str(e),
            )

    rows: list[dict[str, Any]] = []
    gross = 0.0
    recv = 0.0
    pay = 0.0
    for s in seg_models:
        # Prefer equity; if only EV given, treat as equity contribution only when bridge already done
        if s.equity_value is not None:
            val = float(s.equity_value)
            basis = "EQUITY"
        else:
            val = float(s.ev_value)  # type: ignore[arg-type]
            basis = "EV_AS_EQUITY_UNBRIDGED"
            flags.append(f"SEGMENT_EV_UNBRIDGED_{s.segment_id}")
        gross += val
        recv += float(s.inter_segment_receivable)
        pay += float(s.inter_segment_payable)
        rows.append({
            "segment_id": s.segment_id,
            "method": s.method,
            "value": val,
            "basis": basis,
            "inter_segment_receivable": s.inter_segment_receivable,
            "inter_segment_payable": s.inter_segment_payable,
            "notes": s.notes,
        })

    implied_elim = recv - pay
    if inter_segment_elimination is None:
        elimination = implied_elim
        flags.append("INTER_SEGMENT_ELIMINATION_FROM_SEGMENT_CLAIMS")
    else:
        elimination = float(inter_segment_elimination)
        if abs(elimination - implied_elim) > 1e-6 * max(1.0, abs(implied_elim), abs(elimination)):
            return SotpResult(
                valid=False,
                invalid_reason="INTER_SEGMENT_UNRECONCILED",
                unsupported=True,
                data_gap=["inter_segment_elimination"],
                segments=rows,
                reconciliation={
                    "implied_from_segment_claims": implied_elim,
                    "provided_elimination": elimination,
                },
                assumptions=assumptions,
                flags=flags + ["INTER_SEGMENT_MISMATCH"],
                detail=(
                    f"inter-segment elimination {elimination} != implied {implied_elim} "
                    "from segment receivables/payables"
                ),
            )

    hd_model: HoldingDiscount | None
    if holding_discount is None:
        if require_holding_discount_declared:
            return SotpResult(
                valid=False,
                invalid_reason="HOLDING_DISCOUNT_UNDECLARED_PLUG",
                unsupported=True,
                data_gap=["holding_discount"],
                assumptions=assumptions,
                detail="holding discount/premium must be explicit when required; refusing undisclosed plug",
            )
        hd_model = None
        hd_rate = 0.0
        flags.append("HOLDING_DISCOUNT_NONE_EXPLICIT")
    else:
        hd_model = (
            holding_discount if isinstance(holding_discount, HoldingDiscount)
            else HoldingDiscount(**holding_discount)
        )
        hd_rate = float(hd_model.rate)
        flags.append("HOLDING_DISCOUNT_EXPLICIT")

    group = float(group_costs_pv or 0.0)
    debt = float(parent_debt or 0.0)
    minority = float(minority_interest or 0.0)
    non_op = float(non_operating_assets or 0.0)

    # Gross equity before holding discount:
    # sum(segment equity) - inter-segment elim - group costs - parent debt - minorities + non-op assets
    pre_hd = gross - elimination - group - debt - minority + non_op
    equity = pre_hd * (1.0 - hd_rate)
    if not math.isfinite(equity):
        return SotpResult(
            valid=False, invalid_reason="NONFINITE_SOTP", unsupported=True,
            data_gap=["nonfinite"], assumptions=assumptions, flags=flags,
        )

    recon = {
        "sum_segment_equity": gross,
        "inter_segment_elimination": elimination,
        "group_costs_pv": group,
        "parent_debt": debt,
        "minority_interest": minority,
        "non_operating_assets": non_op,
        "equity_before_holding_discount": pre_hd,
        "holding_discount_rate": hd_rate,
        "equity_after_holding_discount": equity,
        "value_per_share": (equity / diluted_shares) if diluted_shares and diluted_shares > 0 else None,
        "identity": (
            "sum(segments) - inter_segment_elim - group_costs - parent_debt "
            "- minorities + non_op_assets, then × (1 - holding_discount)"
        ),
    }
    return SotpResult(
        valid=True,
        unsupported=False,
        data_gap=[],
        equity_value=equity,
        gross_segment_equity=gross,
        reconciliation=recon,
        segments=rows,
        holding_discount=hd_model.model_dump(mode="json") if hd_model else {
            "rate": 0.0, "uncertain": False, "rationale": "none_explicit",
        },
        flags=sorted(set(flags)),
        assumptions=assumptions,
        detail=f"SOTP equity={equity:.4f} from {len(seg_models)} segments; hd={hd_rate:.4f}",
    )
