"""VMS-0.1 — standalone valuation & conditional return engine.

Phase 0 scope only: contracts, config validation, run metadata, deterministic
seeding and an offline smoke demo. No valuation logic exists yet.
"""

__version__ = "0.1.0.dev0"

#: Version of the persisted artifact / data-contract schema.
SCHEMA_VERSION = "vms-0.1.phase1"

#: Phase marker embedded in artifacts so nobody mistakes smoke output for a valuation.
IMPLEMENTED_PHASE = "PHASE_1"
