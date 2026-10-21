"""ValuationMethod plugin protocol (SPEC §11.1).

Phase 2 defined the contract with stubs. Phase 4 plugins compute values only
after hard eligibility gates pass. Placeholder ``FinancialPathBundle`` remains
for stub refusal; real methods require ``statements.paths.FinancialPathBundle``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from vms.profiles.report import ProfileReport
from vms.schemas.contracts import (
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)

if TYPE_CHECKING:
    from vms.methods.eligibility import EligibilityResult
    from vms.schemas.config import LoadedConfig


class ValuationContext(BaseModel):
    """Routing / eligibility context. ``loaded`` carries WACC/TV assumptions for Phase 4+."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    instrument_id: str
    as_of: str
    target: ValuationTarget
    profile: ProfileReport
    available_fields: frozenset[str] = Field(default_factory=frozenset)
    peer_count: int = 0
    data_quality_blocked: bool = False
    # Phase 4: optional LoadedConfig for discount-rate / TV assumptions (not serialized as claim)
    loaded: Any = Field(default=None, description="LoadedConfig | None; not part of investment claim")
    # Optional history for DDM payout gates when path bundle is not yet available
    dividend_history: tuple[float, ...] = ()
    net_income_history: tuple[float, ...] = ()
    # Phase 5: subject fundamentals + PIT peer rows for relative multiples
    subject_metrics: dict[str, Any] = Field(default_factory=dict)
    peer_observations: tuple[Any, ...] = Field(default_factory=tuple)
    # Phase 6: RIM / NAV / SOTP structured inputs (schedules; never inferred from book alone)
    rim_inputs: dict[str, Any] = Field(default_factory=dict)
    nav_inputs: dict[str, Any] = Field(default_factory=dict)
    sotp_inputs: dict[str, Any] = Field(default_factory=dict)


class MethodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    assumptions: dict[str, Any] = Field(default_factory=dict)


class MethodResult(BaseModel):
    """Method-specific result. Empty ``values`` when ineligible/failed — never a fabricated estimate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    status: MethodEligibilityStatus
    reason_codes: list[str] = Field(default_factory=list)
    detail: str = ""
    output_basis: list[OutputBasis] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class MethodDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method_id: str
    messages: list[str] = Field(default_factory=list)


class FinancialPathBundle(BaseModel):
    """Placeholder until a statements path bundle is supplied (Phase 3+).

    Presence of this empty shell must not unlock valuation math.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_note: str = "PHASE2_NO_PATHS"
    n_paths: int = 0


@runtime_checkable
class ValuationMethod(Protocol):
    method_id: str
    version: str

    def eligibility(self, context: ValuationContext) -> EligibilityResult: ...

    def value_paths(
        self,
        context: ValuationContext,
        financial_paths: Any,
        config: MethodConfig,
    ) -> MethodResult: ...

    def diagnostics(self, result: MethodResult) -> MethodDiagnostics: ...
