"""FCFF DCF method plugin (SPEC §12.1, §12.8). Discount at WACC; EV→equity bridge only here."""

from __future__ import annotations

from typing import Any

from vms.equity_bridge.bridge import bridge_ev_to_equity
from vms.methods.cash_flow.common import (
    agg_floats,
    append_gate,
    base_eligibility,
    flag_exclusion,
    horizon_bridge_inputs,
    is_statement_bundle,
    ordered_years,
    point_wacc,
    rate_sensitivities,
    series_for,
    valid_records,
)
from vms.methods.eligibility import EligibilityResult, GateReason
from vms.methods.protocol import MethodConfig, MethodDiagnostics, MethodResult, ValuationContext
from vms.schemas.config import LoadedConfig
from vms.schemas.contracts import MethodEligibilityStatus, MethodRegistryEntry
from vms.statements.cashflows import FCFFSeries
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord
from vms.valuation.dcf import dcf_fcff
from vms.valuation.wacc import WACCInputs


class FcffDcfMethod:
    method_id = "fcff_dcf"
    version = "0.2.0"

    def __init__(self, entry: MethodRegistryEntry) -> None:
        self.entry = entry
        self.method_id = entry.method_id
        self.version = entry.version

    def eligibility(self, context: ValuationContext) -> EligibilityResult:
        elig = base_eligibility(self.entry, context)
        elig = flag_exclusion(self.entry, context, elig)
        # Discount-rate coherence: need LoadedConfig or refuse at value time
        if context.loaded is None:
            elig = append_gate(elig, GateReason(
                code="DISCOUNT_RATE_INPUTS",
                detail="LoadedConfig absent at eligibility; will require at value_paths",
                passed=True,  # soft at gate; hard at value
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
        if not is_statement_bundle(financial_paths):
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=["PATH_BUNDLE_REQUIRED"],
                detail="FCFF DCF requires statements.FinancialPathBundle",
                output_basis=list(self.entry.output_basis),
            )
        loaded: LoadedConfig | None = context.loaded
        if loaded is None:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.FAILED,
                reason_codes=["MISSING_LOADED_CONFIG"],
                detail="WACC/TV assumptions require LoadedConfig on ValuationContext",
                output_basis=list(self.entry.output_basis),
            )
        return self._value(context, financial_paths, loaded, config)

    def _value(
        self,
        context: ValuationContext,
        bundle: FinancialPathBundle,
        loaded: LoadedConfig,
        config: MethodConfig,
    ) -> MethodResult:
        wacc_point = point_wacc(loaded)
        tv_cfg = loaded.config.terminal_value
        g = float(config.assumptions.get("terminal_growth", tv_cfg.terminal_growth))
        rate_shock = float(config.assumptions.get("wacc_shock", getattr(loaded.config.sensitivity, "wacc_shock", 0.01)))
        g_shock = float(config.assumptions.get(
            "terminal_growth_shock", getattr(loaded.config.sensitivity, "terminal_growth_shock", 0.005),
        ))

        path_rows: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for rec in valid_records(bundle):
            row = self._one(rec, loaded, wacc_point, g)
            if row["status"] == "VALID":
                path_rows.append(row)
            else:
                failed.append(row)

        if not path_rows:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.FAILED,
                reason_codes=["PATH_FAILURE", "NO_VALID_DCF_PATHS"],
                detail=f"all paths rejected; sample={failed[:3]}",
                output_basis=list(self.entry.output_basis),
                values={"n_valid": 0, "n_failed": len(failed), "failed": failed[:20]},
                diagnostics={"discount_rate_kind": "WACC", "wacc": wacc_point.model_dump(mode="json")},
            )

        def recompute(rate: float, gg: float) -> float | None:
            # Sensitivity on central / first valid path FCFF series
            sample = path_rows[0]
            fcff = FCFFSeries(years=sample["years"], values=sample["fcff_values"])
            w = wacc_point.model_copy(update={"wacc": rate})
            r = dcf_fcff(fcff=fcff, wacc_inputs=w, tv_cfg=tv_cfg, g=gg)
            return r.enterprise_value if r.valid else None

        sens = rate_sensitivities(
            base_rate=wacc_point.wacc, g=g, tv_cfg=tv_cfg, recompute=recompute,
            rate_shock=rate_shock, g_shock=g_shock,
        )
        values = {
            "discount_rate_kind": "WACC",
            "wacc": wacc_point.wacc,
            "cost_of_equity_component": wacc_point.cost_of_equity,
            "terminal_growth": g,
            "n_valid": len(path_rows),
            "n_failed": len(failed),
            "enterprise_value": agg_floats(r["enterprise_value"] for r in path_rows),
            "equity_value": agg_floats(r["equity_value"] for r in path_rows),
            "value_per_share": agg_floats(r["value_per_share"] for r in path_rows),
            "tv_fraction": agg_floats(r["tv_fraction"] for r in path_rows),
            "sensitivities": sens,
            "bridge_components_sample": path_rows[0].get("bridge_components"),
            "wacc_provenance": wacc_point.provenance,
            "failed_reasons": sorted({f.get("invalid_reason") for f in failed if f.get("invalid_reason")}),
        }
        flags = sorted({fl for r in path_rows for fl in r.get("flags", [])})
        return MethodResult(
            method_id=self.method_id,
            status=MethodEligibilityStatus.VALID,
            reason_codes=[],
            detail=f"FCFF DCF on {len(path_rows)} paths; WACC={wacc_point.wacc:.4f}; g={g:.4f}",
            output_basis=list(self.entry.output_basis),
            values=values,
            diagnostics={"flags": flags, "assumptions": path_rows[0].get("assumptions", [])},
        )

    def _one(
        self,
        rec: FinancialPathRecord,
        loaded: LoadedConfig,
        wacc_template: WACCInputs,
        g: float,
    ) -> dict[str, Any]:
        years = ordered_years(rec)
        if not years:
            return {"path_id": rec.path_id, "status": "REJECTED", "invalid_reason": "EMPTY_FCFF"}
        try:
            vals = series_for(rec, "fcff", years)
        except KeyError:
            return {"path_id": rec.path_id, "status": "REJECTED", "invalid_reason": "EMPTY_FCFF"}
        fcff = FCFFSeries(years=years, values=vals)
        # Path-specific kd/tc when available; weights from template (explicit config)
        wacc_in = wacc_template
        dcf = dcf_fcff(fcff=fcff, wacc_inputs=wacc_in, tv_cfg=loaded.config.terminal_value, g=g)
        if not dcf.valid:
            return {
                "path_id": rec.path_id, "status": "REJECTED", "invalid_reason": dcf.invalid_reason,
                "flags": list(dcf.flags), "years": years, "fcff_values": vals,
            }
        br_in = horizon_bridge_inputs(rec, loaded)
        br = bridge_ev_to_equity(
            enterprise_value=dcf.enterprise_value,
            cash=br_in["cash"], debt=br_in["debt"],
            lease_debt_like=br_in["lease_debt_like"],
            minority_interest_book=br_in["minority_interest_book"],
            other_senior_claims=br_in["other_senior_claims"],
            diluted_shares=br_in["diluted_shares"],
        )
        if not br.valid:
            return {
                "path_id": rec.path_id, "status": "REJECTED", "invalid_reason": br.invalid_reason,
                "flags": list(dcf.flags) + list(br.flags), "years": years, "fcff_values": vals,
            }
        return {
            "path_id": rec.path_id,
            "status": "VALID",
            "years": years,
            "fcff_values": vals,
            "enterprise_value": dcf.enterprise_value,
            "equity_value": br.equity_value,
            "value_per_share": br.value_per_share,
            "tv_fraction": dcf.tv_fraction,
            "pv_fcff": dcf.pv_fcff,
            "pv_tv": dcf.pv_tv,
            "bridge_components": br.components,
            "flags": sorted(set(dcf.flags) | set(br.flags)),
            "assumptions": list(dcf.assumptions) + list(br.assumptions),
            "discount_rate_kind": "WACC",
            "wacc": dcf.wacc,
        }

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics:
        msgs = list(result.reason_codes)
        if result.detail:
            msgs.append(result.detail)
        tv = (result.values or {}).get("tv_fraction") or {}
        if tv.get("mean") is not None:
            msgs.append(f"tv_fraction_mean={tv['mean']}")
        return MethodDiagnostics(method_id=self.method_id, messages=msgs)
