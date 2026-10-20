"""Optional external-system adapters (SPEC §10 / Phase 10).

Core valuation never requires these packages. DSDE integration is optional and
lives behind ``vms.adapters.dsde``.
"""

from vms.adapters.dsde import (DSDEConsumerView, consumer_view_from_result, dsde_availability,
                               try_notify_dsde)

__all__ = [
    "DSDEConsumerView",
    "consumer_view_from_result",
    "dsde_availability",
    "try_notify_dsde",
]
