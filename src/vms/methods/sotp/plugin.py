"""SOTP method plugin (SPEC §12.7)."""

from __future__ import annotations

from typing import Any

from vms.methods.cash_flow.common import append_gate, base_eligibility, flag_exclusion
from vms.methods.eligibility import EligibilityResult, GateReason
from vms.methods.protocol import MethodConfig, MethodDiagnostics, MethodResult, ValuationContext
from vms.methods.sotp.math import compute_sotp
from vms.schemas.contracts import MethodEligibilityStatus, MethodRegistryEntry


class SotpMethod:
    method_id = "sotp"
    version = "0.2.0"

    def __init__(self, entry: MethodRegistryEntry) -> None:
        self.entry = entry
        self.method_id = entry.method_id
        self.version = entry.version

    def _schedule(self, context: ValuationContext, config: MethodConfig) -> dict[str, Any]:
        out: dict[str, Any] = {}
        out.update(dict(context.subject_metrics or {}))
        out.update(dict(context.sotp_inputs or {}))
        out.update(dict(config.assumptions or {}))
        return out

    def eligibility(self, context: ValuationContext) -> EligibilityResult:
        elig = flag_exclusion(self.entry, context, base_eligibility(self.entry, context))
        sched = self._schedule(context, MethodConfig(method_id=self.method_id))
        segs = sched.get("segments") or sched.get("segment_schedule")
        elig = append_gate(elig, GateReason(
            code="SEGMENT_SCHEDULE_NOTED",
            detail=(
                "segment schedule present"
                if segs else
                "segment schedule absent at eligibility (data-gap at value_paths if still missing)"
            ),
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
        segments = sched.get("segments") or sched.get("segment_schedule")
        if not segments:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=["MISSING_SEGMENT_INPUTS"],
                detail="SOTP unsupported without segment schedule; refusing apparently complete value",
                output_basis=list(self.entry.output_basis),
                values={},
                diagnostics={
                    "unsupported": True,
                    "data_gap": ["segments", "group_costs", "parent_debt", "minorities"],
                    "flags": ["APPARENTLY_COMPLETE_SOTP_FORBIDDEN"],
                },
            )
        result = compute_sotp(
            segments=list(segments),
            inter_segment_elimination=sched.get("inter_segment_elimination"),
            group_costs_pv=float(sched.get("group_costs_pv") or 0.0),
            parent_debt=float(sched.get("parent_debt") or sched.get("interest_bearing_debt") or 0.0),
            minority_interest=float(sched.get("minority_interest") or 0.0),
            non_operating_assets=float(sched.get("non_operating_assets") or 0.0),
            holding_discount=sched.get("holding_discount"),
            require_holding_discount_declared=bool(
                sched.get("require_holding_discount_declared", False)
            ),
            diluted_shares=(
                float(sched["diluted_shares"]) if sched.get("diluted_shares") is not None else None
            ),
        )
        if not result.valid:
            return MethodResult(
                method_id=self.method_id,
                status=MethodEligibilityStatus.INELIGIBLE,
                reason_codes=[result.invalid_reason or "MISSING_SEGMENT_INPUTS"],
                detail=result.detail,
                output_basis=list(self.entry.output_basis),
                values={},
                diagnostics={
                    "unsupported": True,
                    "data_gap": list(result.data_gap),
                    "reconciliation": result.reconciliation,
                    "segments": result.segments,
                    "flags": list(result.flags),
                    "assumptions": list(result.assumptions),
                },
            )
        vps = result.reconciliation.get("value_per_share")
        values = {
            "equity_value": {
                "mean": result.equity_value, "p50": result.equity_value,
                "p05": result.equity_value, "p95": result.equity_value, "n": 1,
            },
            "gross_segment_equity": result.gross_segment_equity,
            "reconciliation": result.reconciliation,
            "segments": result.segments,
            "holding_discount": result.holding_discount,
            "value_per_share": (
                {"mean": vps, "p50": vps, "p05": vps, "p95": vps, "n": 1} if vps is not None else None
            ),
            "ev_bridge_applied": False,
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
