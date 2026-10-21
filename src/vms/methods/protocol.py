"""ValuationMethod plugin protocol (SPEC §11.1).

Phase 2 defines the contract. Declared stubs raise structured failures if
``value_paths`` is invoked before implementation (hard-gate enforcement).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from vms.profiles.report import ProfileReport
from vms.schemas.contracts import (
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)


class ValuationContext(BaseModel):
    """Minimal routing context for eligibility (Phase 2; no financial paths yet)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    as_of: str
    target: ValuationTarget
    profile: ProfileReport
    available_fields: frozenset[str] = Field(default_factory=frozenset)
    peer_count: int = 0
    data_quality_blocked: bool = False


class MethodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    assumptions: dict[str, Any] = Field(default_factory=dict)


class MethodResult(BaseModel):
    """Placeholder result shell — Phase 2 never produces values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    status: MethodEligibilityStatus
    reason_codes: list[str] = Field(default_factory=list)
    detail: str = ""
    output_basis: list[OutputBasis] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)


class MethodDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    messages: list[str] = Field(default_factory=list)


class FinancialPathBundle(BaseModel):
    """Opaque placeholder until Phase 3+; presence alone must not unlock valuation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_note: str = "PHASE2_NO_PATHS"
    n_paths: int = 0


@runtime_checkable
class ValuationMethod(Protocol):
    method_id: str
    version: str

    def eligibility(self, context: ValuationContext) -> "EligibilityResult": ...

    def value_paths(
        self,
        context: ValuationContext,
        financial_paths: FinancialPathBundle,
        config: MethodConfig,
    ) -> MethodResult: ...

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics: ...


# Forward ref resolved after eligibility import in registry; keep name for type checkers
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vms.methods.eligibility import EligibilityResult
