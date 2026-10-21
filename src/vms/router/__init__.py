"""Deterministic method router skeleton (VMS-0.2 Phase 2, SPEC §11.4).

Phase 2 lists candidates and hard-gate outcomes only. It never computes method
values and never fabricates a default DCF.
"""

from vms.router.route import RouteReport, route_methods

__all__ = ["RouteReport", "route_methods"]
