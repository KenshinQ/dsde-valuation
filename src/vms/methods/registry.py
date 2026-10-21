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


class MethodRegistry:
    def __init__(self, config: MethodRegistryConfig) -> None:
        self.config = config
        self._plugins: dict[str, ValuationMethod] = {
            e.method_id: DeclaredStubMethod(e) for e in config.methods
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
        return [evaluate_hard_gates(e, context) for e in self.for_target(context.target)]

    def coverage_status(
        self, results: list[EligibilityResult],
    ) -> tuple[str, list[MethodStatusRecord]]:
        """Return gate status code and per-method status rows.

        If no method is eligible-and-implemented, returns INSUFFICIENT_METHOD_COVERAGE
        (SPEC §11.4 / Phase 2 acceptance) — never a default DCF.
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
    # Validate Phase-2 declaration completeness (already enforced by pydantic on load)
    for e in config.methods:
        if not e.supported_targets or not e.output_basis or not e.failure_codes or not e.version:
            raise ValueError(f"method {e.method_id!r} incomplete Phase-2 declaration")
        if e.implementation_status is MethodImplementationStatus.IMPLEMENTED and not e.enabled:
            # Allowed (disabled implemented) but unusual; leave as-is
            pass
    return MethodRegistry(config)
