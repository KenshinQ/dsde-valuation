"""VMS-0.1 — standalone valuation & conditional return engine for China A-shares.

Phases 0–4: contracts, PIT gates, deterministic statements, fundamental regimes,
driver distributions, and correlated path sampling. No DCF / WACC / returns yet.
"""

__version__ = "0.1.0.dev0"

#: Version of the persisted artifact / data-contract schema.
SCHEMA_VERSION = "vms-0.1.phase4"

#: Phase marker embedded in artifacts so nobody mistakes smoke output for a valuation.
IMPLEMENTED_PHASE = "PHASE_4"
