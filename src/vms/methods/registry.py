"""Runtime method registry built from declarative YAML (SPEC §11.1)."""

from __future__ import annotations

from vms.methods.eligibility import DeclaredStubMethod, EligibilityResult, evaluate_hard_gates
from vms.methods.protocol import ValuationContext, ValuationMethod
from vms.schemas.contracts import (
    DataQualityGateStatus,
    MethodImplementationStatus,
    MethodRegistryConfig,
    MethodRegistryEntry,
    MethodStatusRecord,
    ValuationTarget,
)

_PHASE4_PLUGIN_IDS = frozenset({"fcff_dcf", "fcfe_dcf", "ddm"})
_PHASE5_PLUGIN_IDS = frozenset({"pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales"})


def _build_plugin(entry: MethodRegistryEntry) -> ValuationMethod:
    if (
        entry.implementation_status is MethodImplementationStatus.IMPLEMENTED
        and entry.enabled
        and entry.method_id in _PHASE4_PLUGIN_IDS
    ):
        if entry.method_id == "fcff_dcf":
            from vms.methods.cash_flow.fcff_plugin import FcffDcfMethod
            return FcffDcfMethod(entry)
        if entry.method_id == "fcfe_dcf":
            from vms.methods.cash_flow.fcfe_plugin import FcfeDcfMethod
            return FcfeDcfMethod(entry)
        if entry.method_id == "ddm":
            from vms.methods.cash_flow.ddm_plugin import DdmMethod
            return DdmMethod(entry)
    if (
        entry.implementation_status is MethodImplementationStatus.IMPLEMENTED
        and entry.enabled
        and entry.method_id in _PHASE5_PLUGIN_IDS
    ):
        from vms.methods.multiples.plugin_base import (
            EvEbitdaMethod,
            EvEbitMethod,
            EvSalesMethod,
            PbMethod,
            PeMethod,
        )
        return {
            "pe": PeMethod,
            "pb": PbMethod,
            "ev_ebit": EvEbitMethod,
            "ev_ebitda": EvEbitdaMethod,
            "ev_sales": EvSalesMethod,
        }[entry.method_id](entry)
    return DeclaredStubMethod(entry)


class MethodRegistry:
    def __init__(self, config: MethodRegistryConfig) -> None:
        self.config = config
        self._plugins: dict[str, ValuationMethod] = {
            e.method_id: _build_plugin(e) for e in config.methods
        }

    @property
    def entries(self) -> list[MethodRegistryEntry]:
        return list(self.config.methods)

    def get(self, method_id: str) -> MethodRegistryEntry | None:
        for e in self.config.methods:
            if e.method_id == method_id:
                return e
        return None

    def plugin(self, method_id: str) -> ValuationMethod | None:
        return self._plugins.get(method_id)

    def for_target(self, target: ValuationTarget) -> list[MethodRegistryEntry]:
        return [e for e in self.config.methods if target in e.supported_targets]

    def evaluate_all(self, context: ValuationContext) -> list[EligibilityResult]:
        out: list[EligibilityResult] = []
        for e in self.for_target(context.target):
            plugin = self._plugins.get(e.method_id)
            if plugin is not None and hasattr(plugin, "eligibility"):
                out.append(plugin.eligibility(context))
            else:
                out.append(evaluate_hard_gates(e, context))
        return out

    def coverage_status(
        self, results: list[EligibilityResult],
    ) -> tuple[str, list[MethodStatusRecord]]:
        """Return gate status code and per-method status rows.

        If no method is eligible-and-implemented, returns INSUFFICIENT_METHOD_COVERAGE
        (SPEC §11.4) — never a default DCF.
        """
        rows: list[MethodStatusRecord] = []
        any_eligible = False
        for r in results:
            rows.append(MethodStatusRecord(
                method_id=r.method_id,
                status=r.status,
                reason="; ".join(x.code for x in r.reasons if not x.passed) or "gates_passed",
                target=None,
            ))
            if r.eligible:
                any_eligible = True
        if not any_eligible:
            return DataQualityGateStatus.INSUFFICIENT_METHOD_COVERAGE.value, rows
        return "METHODS_ELIGIBLE", rows


def build_registry_from_config(config: MethodRegistryConfig) -> MethodRegistry:
    for e in config.methods:
        if not e.supported_targets or not e.output_basis or not e.failure_codes or not e.version:
            raise ValueError(f"method {e.method_id!r} incomplete Phase-2 declaration")
    return MethodRegistry(config)
