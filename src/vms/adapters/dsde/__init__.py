"""Optional DSDE adapter package (SPEC §18 / Phase 10).

Design rules:
- ``import vms`` and the valuation core never require DSDE installed.
- This package never statically imports ``dsde`` / DSDE-engine / legacy PIT/FTD/DV1
  (enforced by ``tests/unit/test_no_legacy_imports.py``). Optional discovery uses
  ``importlib`` only when a caller explicitly asks.
- Consumers retrieve conditional value/return distributions and uncertainty
  diagnostics through ``DSDEConsumerView`` / ``ReturnDistributionExport``.
"""

from vms.adapters.dsde.contract import (
    DSDE_CONTRACT_VERSION,
    DSDEConsumerView,
    ReturnDistributionExport,
)
from vms.adapters.dsde.export import (
    consumer_view_from_result,
    consumer_view_from_track_b,
    export_return_distribution,
)
from vms.adapters.dsde.notify import dsde_availability, try_notify_dsde

__all__ = [
    "DSDE_CONTRACT_VERSION",
    "DSDEConsumerView",
    "ReturnDistributionExport",
    "consumer_view_from_result",
    "consumer_view_from_track_b",
    "dsde_availability",
    "export_return_distribution",
    "try_notify_dsde",
]
