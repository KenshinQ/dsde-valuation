"""FCFE DCF method plugin (SPEC §12.2). Discount at cost of equity; no EV bridge."""

from __future__ import annotations

from typing import Any

from vms.methods.cash_flow.common import (
    with_midcycle_diagnostics,
    agg_floats,
    base_eligibility,
    flag_exclusion,
    is_statement_bundle,
    ordered_years,
    point_wacc,
    rate_sensitivities,
    series_for,
    valid_records,
)
from vms.methods.cash_flow.equity_dcf import dcf_fcfe
from vms.methods.eligibility import EligibilityResult
from vms.methods.protocol import MethodConfig, MethodDiagnostics, MethodResult, ValuationContext
from vms.schemas.config import LoadedConfig, TerminalValueConfig
from vms.schemas.contracts import MethodEligibilityStatus, MethodRegistryEntry
from vms.statements.cashflows import FCFESeries
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord


class FcfeDcfMethod:
    method_id = "fcfe_dcf"
    version = "0.2.0"

    def __init__(self, entry: MethodRegistryEntry) -> None:
        self.entry = entry
        self.method_id = entry.method_id
        self.version = entry.version

    def eligibility(self, context: ValuationContext) -> EligibilityResult:
        elig = base_eligibility(self.entry, context)
        return flag_exclusion(self.entry, context, elig)

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
                detail="FCFE DCF requires statements.FinancialPathBundle",
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
        return self._value(context, financial_paths, loaded, config)

    def _value(
        self,
        context: ValuationContext,
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
        leverage_flags = self._leverage_diagnostics(bundle)

        path_rows: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for rec in valid_records(bundle):
            row = self._one(rec, ke, tv_cfg, g)
            if row["status"] == "VALID":
                path_rows.append(row)
            else:
                failed.append(row)

        if not path_rows:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.FAILED,
                reason_codes=["PATH_FAILURE", "NO_VALID_DCF_PATHS"],
                detail=f"all FCFE paths rejected; sample={failed[:3]}",
                output_basis=list(self.entry.output_basis),
                values={"n_valid": 0, "n_failed": len(failed), "failed": failed[:20]},
                diagnostics=with_midcycle_diagnostics(
                    context,
                    config,
                    {
                        "discount_rate_kind": "COST_OF_EQUITY",
                        "cost_of_equity": ke,
                        "leverage_flags": leverage_flags,
                    },
                ),
            )

        def recompute(rate: float, gg: float) -> float | None:
            sample = path_rows[0]
            series = FCFESeries(years=sample["years"], values=sample["fcfe_values"])
            r = dcf_fcfe(fcfe=series, cost_of_equity=rate, tv_cfg=tv_cfg, g=gg)
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
            "leverage_flags": leverage_flags,
            "failed_reasons": sorted({f.get("invalid_reason") for f in failed if f.get("invalid_reason")}),
            "ke_provenance": wacc_point.provenance.get("cost_of_equity"),
        }
        flags = sorted({fl for r in path_rows for fl in r.get("flags", [])} | set(leverage_flags))
        return MethodResult(
            method_id=self.method_id,
            status=MethodEligibilityStatus.VALID,
            reason_codes=[],
            detail=f"FCFE DCF on {len(path_rows)} paths; ke={ke:.4f}; g={g:.4f}; no EV bridge",
            output_basis=list(self.entry.output_basis),
            values=values,
            diagnostics=with_midcycle_diagnostics(
                context,
                config,
                {"flags": flags, "assumptions": path_rows[0].get("assumptions", [])},
            ),
        )

    def _leverage_diagnostics(self, bundle: FinancialPathBundle) -> list[str]:
        flags: list[str] = []
        for rec in valid_records(bundle):
            if "INCOHERENT_NET_BORROWING" in (rec.flags or []):
                flags.append("INCOHERENT_NET_BORROWING")
            if rec.net_borrowing and any(abs(v) > 1e12 for v in rec.net_borrowing.values()):
                flags.append("NET_BORROWING_EXTREME")
        return sorted(set(flags))

    def _one(
        self,
        rec: FinancialPathRecord,
        ke: float,
        tv_cfg: TerminalValueConfig,
        g: float,
    ) -> dict[str, Any]:
        years = ordered_years(rec)
        if not years:
            return {"path_id": rec.path_id, "status": "REJECTED", "invalid_reason": "EMPTY_CASHFLOWS"}
        try:
            vals = series_for(rec, "fcfe", years)
        except KeyError:
            return {"path_id": rec.path_id, "status": "REJECTED", "invalid_reason": "EMPTY_CASHFLOWS"}
        series = FCFESeries(years=years, values=vals)
        dcf = dcf_fcfe(fcfe=series, cost_of_equity=ke, tv_cfg=tv_cfg, g=g)
        if not dcf.valid:
            return {
                "path_id": rec.path_id, "status": "REJECTED", "invalid_reason": dcf.invalid_reason,
                "flags": list(dcf.flags), "years": years, "fcfe_values": vals,
            }
        shares = rec.shares.get(str(years[-1]))
        vps = (dcf.equity_value / shares) if shares and shares > 0 else None
        return {
            "path_id": rec.path_id,
            "status": "VALID",
            "years": years,
            "fcfe_values": vals,
            "equity_value": dcf.equity_value,
            "value_per_share": vps,
            "tv_fraction": dcf.tv_fraction,
            "pv_cashflows": dcf.pv_cashflows,
            "pv_tv": dcf.pv_tv,
            "flags": list(dcf.flags),
            "assumptions": list(dcf.assumptions),
            "discount_rate_kind": "COST_OF_EQUITY",
            "cost_of_equity": ke,
            "ev_bridge_applied": False,
        }

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics:
        msgs = list(result.reason_codes)
        if result.detail:
            msgs.append(result.detail)
        msgs.append("ev_bridge_applied=false")
        return MethodDiagnostics(method_id=self.method_id, messages=msgs)
