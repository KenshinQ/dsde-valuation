"""Walk-forward evaluation and calibration (SPEC §17, Phase 11)."""

from vms.evaluation.errors import RandomSplitProhibitedError
from vms.evaluation.protocol import (
    assert_weights_unchanged,
    freeze_weights_before_test,
    require_chronological,
)
from vms.evaluation.run import EvaluationReport, run_evaluation
from vms.evaluation.universe import UniverseConfig, load_universe

__all__ = [
    "EvaluationReport",
    "RandomSplitProhibitedError",
    "UniverseConfig",
    "assert_weights_unchanged",
    "freeze_weights_before_test",
    "load_universe",
    "require_chronological",
    "run_evaluation",
]
