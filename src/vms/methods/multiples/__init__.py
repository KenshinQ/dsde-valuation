"""Phase 5 relative valuation methods (SPEC §12.5–12.6, §20 Phase 5).

Plugins: pe, pb, ev_ebit, ev_ebitda, ev_sales. PIT peer sets, robust aggregation,
denominator gates, EV/equity bridge discipline. No ensemble blend (Phase 8).
Engineering ≠ investment alpha.
"""

from vms.methods.multiples.aggregate import AggregateResult, aggregate_multiples
from vms.methods.multiples.apply import MultipleValueResult, apply_equity_multiple, apply_ev_multiple
from vms.methods.multiples.definitions import METRIC_DEFINITIONS, MetricDefinition, get_definition
from vms.methods.multiples.denominators import DenominatorDecision, check_denominator
from vms.methods.multiples.peers import PeerFilterConfig, PeerSetReport, build_peer_set
from vms.methods.multiples.midcycle import (
    MidCycleConfidence,
    MidCycleEstimate,
    estimate_mid_cycle_denominator,
    injectable_mid_denominator,
    passthrough_midcycle_diagnostics,
    resolve_cyclical_midcycle,
)
from vms.methods.multiples.plugin_base import (
    EvEbitdaMethod,
    EvEbitMethod,
    EvSalesMethod,
    PbMethod,
    PeMethod,
)
from vms.methods.multiples.run import (
    PHASE5_MULTIPLE_METHODS,
    MultiplesRunBundle,
    run_eligible_multiple_methods,
)

__all__ = [
    "METRIC_DEFINITIONS",
    "MetricDefinition",
    "get_definition",
    "DenominatorDecision",
    "check_denominator",
    "aggregate_multiples",
    "AggregateResult",
    "build_peer_set",
    "PeerSetReport",
    "PeerFilterConfig",
    "apply_equity_multiple",
    "apply_ev_multiple",
    "MultipleValueResult",
    "PeMethod",
    "PbMethod",
    "EvEbitMethod",
    "EvEbitdaMethod",
    "EvSalesMethod",
    "PHASE5_MULTIPLE_METHODS",
    "MultiplesRunBundle",
    "run_eligible_multiple_methods",
    "MidCycleConfidence",
    "MidCycleEstimate",
    "estimate_mid_cycle_denominator",
    "resolve_cyclical_midcycle",
    "injectable_mid_denominator",
    "passthrough_midcycle_diagnostics",
]
