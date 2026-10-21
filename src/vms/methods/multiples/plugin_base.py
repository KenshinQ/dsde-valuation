"""Shared ValuationMethod plugin base for Phase-5 multiples."""

from __future__ import annotations

from typing import Any

from vms.methods.multiples.common import eligibility_with_denominator_hint, run_multiple_method
from vms.methods.multiples.definitions import get_definition
from vms.methods.protocol import MethodConfig, MethodDiagnostics, MethodResult, ValuationContext
from vms.schemas.contracts import MethodRegistryEntry


class MultipleMethodBase:
    method_id: str = ""
    version: str = "0.2.0"

    def __init__(self, entry: MethodRegistryEntry) -> None:
        self.entry = entry
        self.method_id = entry.method_id
        self.version = entry.version
        self.definition = get_definition(entry.method_id)

    def eligibility(self, context: ValuationContext):
        return eligibility_with_denominator_hint(self.entry, context, self.definition)

    def value_paths(
        self,
        context: ValuationContext,
        financial_paths: Any,
        config: MethodConfig,
    ) -> MethodResult:
        # Multiples use current subject metrics + PIT peers; financial_paths ignored
        # (path-wise terminal multiples are Phase 9 market-pricing).
        _ = financial_paths
        return run_multiple_method(entry=self.entry, context=context, config=config)

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics:
        msgs = list(result.reason_codes)
        if result.detail:
            msgs.append(result.detail)
        flags = (result.values or {}).get("flags") or []
        msgs.extend(str(f) for f in flags)
        return MethodDiagnostics(method_id=self.method_id, messages=msgs)


class PeMethod(MultipleMethodBase):
    method_id = "pe"


class PbMethod(MultipleMethodBase):
    method_id = "pb"


class EvEbitMethod(MultipleMethodBase):
    method_id = "ev_ebit"


class EvEbitdaMethod(MultipleMethodBase):
    method_id = "ev_ebitda"


class EvSalesMethod(MultipleMethodBase):
    method_id = "ev_sales"
