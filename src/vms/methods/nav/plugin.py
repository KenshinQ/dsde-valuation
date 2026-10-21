"""NAV method plugin (SPEC §12.7)."""

from __future__ import annotations

from typing import Any

from vms.methods.cash_flow.common import append_gate, base_eligibility, flag_exclusion
from vms.methods.eligibility import EligibilityResult, GateReason
from vms.methods.nav.math import NavLine, book_totals_are_not_nav, compute_nav
from vms.methods.protocol import MethodConfig, MethodDiagnostics, MethodResult, ValuationContext
from vms.schemas.contracts import MethodEligibilityStatus, MethodRegistryEntry


class NavMethod:
    method_id = "nav"
    version = "0.2.0"

    def __init__(self, entry: MethodRegistryEntry) -> None:
        self.entry = entry
        self.method_id = entry.method_id
        self.version = entry.version

    def _schedule(self, context: ValuationContext, config: MethodConfig) -> dict[str, Any]:
        out: dict[str, Any] = {}
        out.update(dict(context.subject_metrics or {}))
        out.update(dict(context.nav_inputs or {}))
        out.update(dict(config.assumptions or {}))
        return out

    def eligibility(self, context: ValuationContext) -> EligibilityResult:
        elig = flag_exclusion(self.entry, context, base_eligibility(self.entry, context))
        sched = self._schedule(context, MethodConfig(method_id=self.method_id))
        assets = sched.get("assets") or sched.get("asset_schedule")
        if not assets:
            # Still hard-gate eligible if required_fields present; value_paths returns data-gap.
            # Soft note only — missing schedule is a method-level unsupported, not profile fail.
            elig = append_gate(elig, GateReason(
                code="ASSET_SCHEDULE_PRESENT",
                detail="asset fair-value schedule absent at eligibility time (may still be supplied in assumptions)",
                passed=True,
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
        sched = self._schedule(context, config)
        assets = sched.get("assets") or sched.get("asset_schedule")
        claims = sched.get("claims") or sched.get("claim_schedule") or ()
        if not assets:
            # Visible unsupported — never invent NAV from book totals
            ta = sched.get("total_assets")
            tl = sched.get("total_liabilities")
            refused = book_totals_are_not_nav(
                total_assets=float(ta) if ta is not None else None,
                total_liabilities=float(tl) if tl is not None else None,
            )
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=["MISSING_ASSET_INPUTS", refused.invalid_reason or "UNSUPPORTED"],
                detail=refused.detail,
                output_basis=list(self.entry.output_basis),
                values={},
                diagnostics={
                    "unsupported": True,
                    "data_gap": list(refused.data_gap),
                    "reconciliation": refused.reconciliation,
                    "flags": list(refused.flags),
                    "assumptions": list(refused.assumptions),
                },
            )
        result = compute_nav(
            assets=list(assets),
            claims=list(claims),
            corporate_overhead_pv=float(sched.get("corporate_overhead_pv") or 0.0),
            disposal_tax=float(sched.get("disposal_tax") or 0.0),
            diluted_shares=(
                float(sched["diluted_shares"]) if sched.get("diluted_shares") is not None else None
            ),
        )
        if not result.valid:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=[result.invalid_reason or "MISSING_ASSET_INPUTS"],
                detail=result.detail,
                output_basis=list(self.entry.output_basis),
                values={},
                diagnostics={
                    "unsupported": True,
                    "data_gap": list(result.data_gap),
                    "lines": result.lines,
                    "flags": list(result.flags),
                    "assumptions": list(result.assumptions),
                },
            )
        vps = result.reconciliation.get("value_per_share")
        values = {
            "nav_equity": {
                "mean": result.nav_equity, "p50": result.nav_equity,
                "p05": result.nav_equity, "p95": result.nav_equity, "n": 1,
            },
            "gross_asset_fair": result.gross_asset_fair,
            "gross_claim_fair": result.gross_claim_fair,
            "reconciliation": result.reconciliation,
            "lines": result.lines,
            "value_per_share": (
                {"mean": vps, "p50": vps, "p05": vps, "p95": vps, "n": 1} if vps is not None else None
            ),
            "ev_bridge_applied": False,
            "book_equated_to_fair": False,
        }
        return MethodResult(
            method_id=self.method_id,
            status=MethodEligibilityStatus.VALID,
            reason_codes=[],
            detail=result.detail,
            output_basis=list(self.entry.output_basis),
            values=values,
            diagnostics={
                "flags": list(result.flags),
                "assumptions": list(result.assumptions),
                "unsupported": False,
                "data_gap": [],
            },
        )

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics:
        msgs = list(result.reason_codes)
        if result.detail:
            msgs.append(result.detail)
        return MethodDiagnostics(method_id=self.method_id, messages=msgs)
