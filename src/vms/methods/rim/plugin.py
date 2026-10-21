"""Residual Income method plugin (SPEC §12.4). Equity-side; no EV bridge."""

from __future__ import annotations

from typing import Any

from vms.methods.cash_flow.common import (
    append_gate,
    base_eligibility,
    flag_exclusion,
    is_statement_bundle,
    point_wacc,
)
from vms.methods.eligibility import EligibilityResult, GateReason
from vms.methods.protocol import MethodConfig, MethodDiagnostics, MethodResult, ValuationContext
from vms.methods.rim.math import residual_income_value
from vms.schemas.config import LoadedConfig
from vms.schemas.contracts import MethodEligibilityStatus, MethodRegistryEntry


def _num(d: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                return None
    return None


def _seq(d: dict[str, Any], key: str) -> list[float] | None:
    v = d.get(key)
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return [float(v)]
    return [float(x) for x in v]


def _extract_from_paths(financial_paths: Any) -> dict[str, Any] | None:
    """Pull NI / book equity / distributions from a statement path central projection."""
    if not is_statement_bundle(financial_paths):
        return None
    rec = financial_paths.central
    if rec is None or rec.projection is None:
        return None
    proj = rec.projection
    years = list(proj.years)
    if not years:
        return None
    items = proj.items

    def series(name: str) -> list[float] | None:
        out = []
        for y in years:
            key = f"{name}@{y}"
            if key not in items:
                return None
            out.append(float(items[key].value))
        return out

    ni = series("parent_net_income") or series("net_income")
    te = series("total_equity")
    div = series("dividends_paid") or series("distributions_to_shareholders")
    if ni is None or te is None:
        return None
    # Beginning book = equity just before first forecast year ≈ prior year equity if present
    y0 = financial_paths.base_year
    be0_key = f"total_equity@{y0}"
    if be0_key in items:
        be0 = float(items[be0_key].value)
    else:
        # Fall back: first year ending less NI + div approx — prefer explicit
        be0 = te[0] - ni[0] + (div[0] if div else 0.0)
    issuance = series("share_issuance_proceeds")
    buybacks = series("share_repurchases")
    net_iss = None
    if issuance is not None or buybacks is not None:
        iss = issuance or [0.0] * len(years)
        bb = buybacks or [0.0] * len(years)
        net_iss = [iss[i] - bb[i] for i in range(len(years))]
    oci = series("oci") or series("other_comprehensive_income")
    shares = None
    if rec.shares:
        shares = float(rec.shares.get(str(years[-1])) or next(iter(rec.shares.values()), 0) or 0) or None
    return {
        "book_equity_0": be0,
        "net_income": ni,
        "dividends": div,
        "net_issuance": net_iss,
        "oci": oci,
        "years": years,
        "diluted_shares": shares,
        "zeros_explicit": oci is None and net_iss is None,
    }


class ResidualIncomeMethod:
    method_id = "residual_income"
    version = "0.2.0"

    def __init__(self, entry: MethodRegistryEntry) -> None:
        self.entry = entry
        self.method_id = entry.method_id
        self.version = entry.version

    def eligibility(self, context: ValuationContext) -> EligibilityResult:
        elig = flag_exclusion(self.entry, context, base_eligibility(self.entry, context))
        # Method-level: book equity must be present in fields or rim_inputs
        be = None
        if context.rim_inputs:
            be = _num(context.rim_inputs, "book_equity_0", "total_equity", "book_equity")
        if be is None:
            be = _num(context.subject_metrics, "total_equity", "book_equity", "book_equity_0")
        if be is None and "total_equity" not in context.available_fields:
            elig = append_gate(elig, GateReason(
                code="MISSING_BOOK_EQUITY",
                detail="book equity not in rim_inputs/subject_metrics/available_fields",
                passed=False,
            ))
        elif be is not None and be < 0:
            elig = append_gate(elig, GateReason(
                code="NEGATIVE_BOOK_EQUITY",
                detail=f"book_equity={be}",
                passed=False,
            ))
        return elig

    def value_paths(
        self,
        context: ValuationContext,
        financial_paths: Any,
        config: MethodConfig,
    ) -> MethodResult:
        elig = self.eligibility(context)
        if not elig.eligible:
            codes = [r.code for r in elig.reasons if not r.passed]
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=codes or ["HARD_GATE_FAILED"],
                detail="; ".join(r.detail for r in elig.reasons if not r.passed),
                output_basis=list(self.entry.output_basis),
            )
        loaded: LoadedConfig | None = context.loaded
        inputs: dict[str, Any] = {}
        extracted = _extract_from_paths(financial_paths)
        if extracted:
            inputs.update(extracted)
        inputs.update(dict(context.subject_metrics or {}))
        inputs.update(dict(context.rim_inputs or {}))
        inputs.update(dict(config.assumptions or {}))

        be0 = _num(inputs, "book_equity_0", "total_equity", "book_equity")
        ni = _seq(inputs, "net_income") or _seq(inputs, "parent_net_income")
        if ni is None and "roe" in inputs and be0 is not None:
            roe = _seq(inputs, "roe")
            if roe:
                # Build NI from ROE * beginning book iteratively — only if single ROE applied to BE0
                ni = [float(roe[0]) * float(be0)]
                for r in roe[1:]:
                    # placeholder; full path built inside math via clean surplus if divs given
                    ni.append(float(r) * float(be0))  # rough; prefer explicit NI
        if be0 is None:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=["MISSING_BOOK_EQUITY"],
                detail="RIM requires current book equity",
                output_basis=list(self.entry.output_basis),
                diagnostics={"unsupported": True, "data_gap": ["book_equity_0"]},
            )
        if not ni:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=["MISSING_NET_INCOME_FORECAST", "CLEAN_SURPLUS_UNASSESSABLE"],
                detail="RIM requires net-income (or ROE) forecast; refusing to invent earnings",
                output_basis=list(self.entry.output_basis),
                diagnostics={"unsupported": True, "data_gap": ["net_income"]},
            )

        ke = _num(inputs, "cost_of_equity")
        if ke is None and loaded is not None:
            ke = point_wacc(loaded).cost_of_equity
        if ke is None:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.FAILED,
                reason_codes=["MISSING_COST_OF_EQUITY"],
                detail="cost of equity required (assumptions or LoadedConfig.valuation)",
                output_basis=list(self.entry.output_basis),
            )

        tv_cfg = loaded.config.terminal_value if loaded is not None else None
        g = float(inputs.get(
            "terminal_growth",
            tv_cfg.terminal_growth if tv_cfg is not None else 0.02,
        ))
        max_g = float(inputs.get(
            "max_terminal_growth",
            tv_cfg.max_terminal_growth if tv_cfg is not None else 0.05,
        ))
        min_margin = float(inputs.get(
            "min_ke_minus_g",
            tv_cfg.min_wacc_minus_g if tv_cfg is not None else 0.005,
        ))
        zeros_explicit = bool(inputs.get("zeros_explicit", False))
        years_arg = None
        if "years" in inputs and inputs["years"] is not None:
            years_arg = [int(x) for x in inputs["years"]]
        result = residual_income_value(
            book_equity_0=be0,
            net_income=ni,
            cost_of_equity=ke,
            dividends=_seq(inputs, "dividends") or _seq(inputs, "dividends_paid"),
            net_issuance=_seq(inputs, "net_issuance"),
            oci=_seq(inputs, "oci"),
            years=years_arg,
            terminal_growth=g,
            max_terminal_growth=max_g,
            min_ke_minus_g=min_margin,
            diluted_shares=_num(inputs, "diluted_shares", "shares"),
            ending_book_observed=_num(inputs, "ending_book_observed", "ending_book_equity"),
            zeros_explicit=zeros_explicit,
            adjust_to_clean_surplus=bool(inputs.get("adjust_to_clean_surplus", False)),
            max_deviation_ratio=float(inputs.get("max_deviation_ratio", 0.05)),
            goodwill=_num(inputs, "goodwill"),
            goodwill_haircut=float(inputs.get("goodwill_haircut", 0.0) or 0.0),
        )
        if not result.valid:
            status = MethodEligibilityStatus.INELIGIBLE
            if result.invalid_reason in {"KE_G_MARGIN_FAIL", "NONFINITE_RIM", "TERMINAL_GROWTH_ABOVE_MAX"}:
                status = MethodEligibilityStatus.FAILED
            return MethodResult(
                method_id=self.method_id,
                status=status,
                reason_codes=[result.invalid_reason or "RIM_FAILED"],
                detail=(result.clean_surplus.detail if result.clean_surplus else result.invalid_reason) or "",
                output_basis=list(self.entry.output_basis),
                values={},
                diagnostics={
                    "clean_surplus": result.clean_surplus.model_dump(mode="json") if result.clean_surplus else None,
                    "flags": list(result.flags),
                    "unsupported": result.invalid_reason in {
                        "CLEAN_SURPLUS_UNASSESSABLE", "MISSING_BOOK_EQUITY", "MISSING_NET_INCOME_FORECAST",
                    },
                    "data_gap": [result.invalid_reason] if result.invalid_reason else [],
                    "ev_bridge_applied": False,
                },
            )
        values = {
            "discount_rate_kind": "COST_OF_EQUITY",
            "cost_of_equity": result.cost_of_equity,
            "terminal_growth": result.g,
            "book_equity_0": result.book_equity_0,
            "equity_value": {
                "mean": result.equity_value, "p50": result.equity_value,
                "p05": result.equity_value, "p95": result.equity_value, "n": 1,
            },
            "value_per_share": (
                {"mean": result.value_per_share, "p50": result.value_per_share,
                 "p05": result.value_per_share, "p95": result.value_per_share, "n": 1}
                if result.value_per_share is not None else None
            ),
            "pv_ri": result.pv_ri,
            "pv_tv": result.pv_tv,
            "tv_fraction": result.tv_fraction,
            "residual_income": list(result.residual_income),
            "book_path": list(result.book_path),
            "years": list(result.years),
            "ev_bridge_applied": False,
            "clean_surplus": result.clean_surplus.model_dump(mode="json") if result.clean_surplus else None,
            "formula": "EquityValue = BookEquity_0 + PV(RI) + PV(TV_RI)",
        }
        return MethodResult(
            method_id=self.method_id,
            status=MethodEligibilityStatus.VALID,
            reason_codes=[],
            detail=(
                f"RIM equity={result.equity_value:.4f}; ke={result.cost_of_equity:.4f}; "
                f"g={result.g:.4f}; CS={result.clean_surplus.treatment if result.clean_surplus else 'n/a'}; "
                "no EV bridge"
            ),
            output_basis=list(self.entry.output_basis),
            values=values,
            diagnostics={
                "flags": list(result.flags),
                "assumptions": list(result.assumptions),
                "ev_bridge_applied": False,
            },
        )

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics:
        msgs = list(result.reason_codes)
        if result.detail:
            msgs.append(result.detail)
        msgs.append("ev_bridge_applied=false")
        return MethodDiagnostics(method_id=self.method_id, messages=msgs)
