"""Dividend Discount Model plugin (SPEC §12.3). Ineligible payout → structured reason, no fabricated dividends."""

from __future__ import annotations

from typing import Any

from vms.methods.cash_flow.common import (
    agg_floats,
    append_gate,
    base_eligibility,
    flag_exclusion,
    is_statement_bundle,
    ordered_years,
    point_wacc,
    rate_sensitivities,
    series_for,
    valid_records,
)
from vms.methods.cash_flow.equity_dcf import ddm_equity, payout_modelable
from vms.methods.eligibility import EligibilityResult, GateReason
from vms.methods.protocol import MethodConfig, MethodDiagnostics, MethodResult, ValuationContext
from vms.schemas.config import LoadedConfig, TerminalValueConfig
from vms.schemas.contracts import MethodEligibilityStatus, MethodRegistryEntry
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord


class DdmMethod:
    method_id = "ddm"
    version = "0.2.0"

    def __init__(self, entry: MethodRegistryEntry) -> None:
        self.entry = entry
        self.method_id = entry.method_id
        self.version = entry.version

    def eligibility(self, context: ValuationContext) -> EligibilityResult:
        elig = base_eligibility(self.entry, context)
        elig = flag_exclusion(self.entry, context, elig)
        # Payout modelability from optional history on context (path-level rechecked at value_paths)
        if context.dividend_history:
            gate = payout_modelable(
                dividends=context.dividend_history,
                net_income=context.net_income_history or None,
            )
            elig = append_gate(elig, GateReason(
                code="PAYOUT_MODELABLE",
                detail=gate.detail,
                passed=gate.modelable,
            ))
            if not gate.modelable:
                # ensure reason codes surface
                for code in gate.reason_codes:
                    if code != "PAYOUT_NOT_MODELABLE":
                        elig = append_gate(elig, GateReason(code=code, detail=gate.detail, passed=False))
        return elig

    def value_paths(
        self,
        context: ValuationContext,
        financial_paths: Any,
        config: MethodConfig,
    ) -> MethodResult:
        elig = self.eligibility(context)
        # Path-based payout gate when bundle present
        if is_statement_bundle(financial_paths):
            path_gate = self._path_payout_gate(financial_paths, config)
            if not path_gate["modelable"]:
                return MethodResult(
                    method_id=self.method_id,
                    status=MethodEligibilityStatus.INELIGIBLE,
                    reason_codes=path_gate["reason_codes"],
                    detail=path_gate["detail"],
                    output_basis=list(self.entry.output_basis),
                    values={},  # never fabricate
                    diagnostics={"payout_gate": path_gate},
                )
        if not elig.eligible:
            codes = [r.code for r in elig.reasons if not r.passed]
            # Prefer payout codes when present
            if any(c in codes for c in ("PAYOUT_MODELABLE", "FLAG_EXCLUSION")):
                pass
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=codes or ["HARD_GATE_FAILED"],
                detail="; ".join(r.detail for r in elig.reasons if not r.passed),
                output_basis=list(self.entry.output_basis),
            )
        if not is_statement_bundle(financial_paths):
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=["PATH_BUNDLE_REQUIRED"],
                detail="DDM requires statements.FinancialPathBundle or refuses with PAYOUT_NOT_MODELABLE",
                output_basis=list(self.entry.output_basis),
            )
        loaded: LoadedConfig | None = context.loaded
        if loaded is None:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.FAILED,
                reason_codes=["MISSING_LOADED_CONFIG"],
                detail="cost-of-equity / TV assumptions require LoadedConfig",
                output_basis=list(self.entry.output_basis),
            )
        return self._value(financial_paths, loaded, config)

    def _path_payout_gate(self, bundle: FinancialPathBundle, config: MethodConfig) -> dict[str, Any]:
        max_cv = float(config.assumptions.get("max_payout_cv", 1.0))
        divs: list[float] = []
        nis: list[float] = []
        for rec in valid_records(bundle):
            years = ordered_years(rec)
            for y in years:
                ys = str(y)
                if ys in rec.dividends:
                    divs.append(float(rec.dividends[ys]))
                if rec.projection is not None:
                    key = f"parent_net_income@{y}"
                    if key in rec.projection.items:
                        nis.append(float(rec.projection.items[key].value))
        gate = payout_modelable(
            dividends=divs,
            net_income=nis if len(nis) == len(divs) and nis else None,
            max_payout_cv=max_cv,
        )
        return {
            "modelable": gate.modelable,
            "reason_codes": gate.reason_codes or (["PAYOUT_NOT_MODELABLE"] if not gate.modelable else []),
            "detail": gate.detail,
            "payout_cv": gate.payout_cv,
            "mean_dividend": gate.mean_dividend,
        }

    def _value(
        self,
        bundle: FinancialPathBundle,
        loaded: LoadedConfig,
        config: MethodConfig,
    ) -> MethodResult:
        wacc_point = point_wacc(loaded)
        ke = wacc_point.cost_of_equity
        tv_cfg = loaded.config.terminal_value
        g = float(config.assumptions.get("terminal_growth", tv_cfg.terminal_growth))
        rate_shock = float(config.assumptions.get("wacc_shock", loaded.config.sensitivity.wacc_shock))
        g_shock = float(config.assumptions.get(
            "terminal_growth_shock", loaded.config.sensitivity.terminal_growth_shock,
        ))
        max_cv = float(config.assumptions.get("max_payout_cv", 1.0))

        path_rows: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for rec in valid_records(bundle):
            row = self._one(rec, ke, tv_cfg, g, max_cv)
            if row["status"] == "VALID":
                path_rows.append(row)
            else:
                failed.append(row)

        # If every path failed for payout reasons → INELIGIBLE not FAILED-with-value
        payout_fails = [f for f in failed if f.get("invalid_reason") in {
            "PAYOUT_NOT_MODELABLE", "ABSENT_DIVIDENDS", "ERRATIC_PAYOUT", "GORDON_STABILITY_FAIL",
        }]
        if not path_rows and payout_fails and len(payout_fails) == len(failed):
            reason = payout_fails[0].get("invalid_reason") or "PAYOUT_NOT_MODELABLE"
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=[reason, "PAYOUT_NOT_MODELABLE"],
                detail="dividends absent/erratic across paths; refusing fabricated dividend stream",
                output_basis=list(self.entry.output_basis),
                values={},
                diagnostics={"failed": failed[:20]},
            )

        if not path_rows:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.FAILED,
                reason_codes=["PATH_FAILURE", "NO_VALID_DDM_PATHS"],
                detail=f"all DDM paths rejected; sample={failed[:3]}",
                output_basis=list(self.entry.output_basis),
                values={"n_valid": 0, "n_failed": len(failed), "failed": failed[:20]},
                diagnostics={"discount_rate_kind": "COST_OF_EQUITY", "cost_of_equity": ke},
            )

        def recompute(rate: float, gg: float) -> float | None:
            sample = path_rows[0]
            r = ddm_equity(
                dividends=sample["dividends"], years=sample["years"],
                cost_of_equity=rate, tv_cfg=tv_cfg, g=gg,
            )
            return r.equity_value if r.valid else None

        sens = rate_sensitivities(
            base_rate=ke, g=g, tv_cfg=tv_cfg, recompute=recompute,
            rate_shock=rate_shock, g_shock=g_shock,
        )
        values = {
            "discount_rate_kind": "COST_OF_EQUITY",
            "cost_of_equity": ke,
            "wacc_not_used": True,
            "terminal_growth": g,
            "n_valid": len(path_rows),
            "n_failed": len(failed),
            "equity_value": agg_floats(r["equity_value"] for r in path_rows),
            "value_per_share": agg_floats(r.get("value_per_share") for r in path_rows),
            "tv_fraction": agg_floats(r["tv_fraction"] for r in path_rows),
            "sensitivities": sens,
            "ev_bridge_applied": False,
            "form": path_rows[0].get("form"),
            "failed_reasons": sorted({f.get("invalid_reason") for f in failed if f.get("invalid_reason")}),
        }
        flags = sorted({fl for r in path_rows for fl in r.get("flags", [])})
        return MethodResult(
            method_id=self.method_id,
            status=MethodEligibilityStatus.VALID,
            reason_codes=[],
            detail=f"DDM on {len(path_rows)} paths; ke={ke:.4f}; g={g:.4f}; no EV bridge",
            output_basis=list(self.entry.output_basis),
            values=values,
            diagnostics={"flags": flags, "assumptions": path_rows[0].get("assumptions", [])},
        )

    def _one(
        self,
        rec: FinancialPathRecord,
        ke: float,
        tv_cfg: TerminalValueConfig,
        g: float,
        max_cv: float,
    ) -> dict[str, Any]:
        years = ordered_years(rec)
        if not years:
            return {"path_id": rec.path_id, "status": "REJECTED", "invalid_reason": "EMPTY_DIVIDENDS"}
        try:
            divs = series_for(rec, "dividends", years)
        except KeyError:
            return {"path_id": rec.path_id, "status": "REJECTED", "invalid_reason": "ABSENT_DIVIDENDS"}
        nis: list[float] = []
        if rec.projection is not None:
            for y in years:
                key = f"parent_net_income@{y}"
                if key in rec.projection.items:
                    nis.append(float(rec.projection.items[key].value))
        ddm = ddm_equity(
            dividends=divs, years=years, cost_of_equity=ke, tv_cfg=tv_cfg, g=g,
            net_income=nis if len(nis) == len(divs) else None, max_payout_cv=max_cv,
        )
        if not ddm.valid:
            return {
                "path_id": rec.path_id, "status": "REJECTED", "invalid_reason": ddm.invalid_reason,
                "flags": list(ddm.flags), "years": years, "dividends": divs,
            }
        shares = rec.shares.get(str(years[-1]))
        vps = (ddm.equity_value / shares) if shares and shares > 0 else None
        return {
            "path_id": rec.path_id,
            "status": "VALID",
            "years": years,
            "dividends": divs,
            "equity_value": ddm.equity_value,
            "value_per_share": vps,
            "tv_fraction": ddm.tv_fraction,
            "form": ddm.form,
            "flags": list(ddm.flags),
            "assumptions": list(ddm.assumptions),
            "discount_rate_kind": "COST_OF_EQUITY",
            "ev_bridge_applied": False,
        }

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics:
        msgs = list(result.reason_codes)
        if result.detail:
            msgs.append(result.detail)
        return MethodDiagnostics(method_id=self.method_id, messages=msgs)
