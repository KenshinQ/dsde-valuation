"""Optional probabilistic hidden-state model: INTERFACE ONLY. NOT IMPLEMENTED in VMS-0.1.

Why not implemented (REGIME-HMM-DEFERRED-v1): a per-company Gaussian HMM with 4 states on 2 features
has about 4x(2 means + 3 covariance terms) + 12 transition parameters (~32). That is more than the
~4-20 observations a single A-share history provides, so it would be over-parameterised. A pooled
cross-sectional HMM needs a panel dataset (Phase 9 data) and is deferred. Selecting ``regimes.model:
hmm`` raises ``RegimeModelNotImplemented``. This is not counted towards Phase 3 acceptance.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from vms.regimes.schemas import FeatureRow, PeriodPosterior


class RegimeModelNotImplemented(NotImplementedError):
    pass


class RegimeModel(ABC):
    """Contract shared by all fundamental regime models: features -> filtered period posteriors."""

    model_id: str
    model_version: str
    status: str = "IMPLEMENTED"

    @abstractmethod
    def filter(self, rows: Sequence[FeatureRow]) -> list[PeriodPosterior]: ...


class HiddenMarkovRegimeModel(RegimeModel):
    model_id = "FUND-HMM"
    model_version = "0"
    status = "NOT_IMPLEMENTED"

    def __init__(self, *_: object, **__: object) -> None:
        raise RegimeModelNotImplemented(
            "regimes.model='hmm' is an interface only in VMS-0.1 (REGIME-HMM-DEFERRED-v1): a per-company HMM is "
            "over-parameterised for ~4-20 observations. Use regimes.model: rule_based.")

    def filter(self, rows: Sequence[FeatureRow]) -> list[PeriodPosterior]:  # pragma: no cover
        raise RegimeModelNotImplemented("HMM not implemented")
