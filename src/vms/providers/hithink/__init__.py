"""HiThink + Eastmoney NOTICE_DATE A-share adapter (provider-neutral LoadResult).

Assumptions: HITHINK-PIT-NOTICE-v1, HITHINK-LATEST-ONLY-v1, HITHINK-UNITS-YUAN-v1,
HITHINK-NO-VENDOR-QFQ-v1, HITHINK-LOCAL-FIRST-v1, HITHINK-CA-DEFER-v1
(see docs/assumptions.md).
"""

from vms.providers.hithink.adapter import HiThinkFetchError, fetch_bundle
from vms.providers.hithink.lab import HiThinkUnavailable

__all__ = ["fetch_bundle", "HiThinkFetchError", "HiThinkUnavailable"]
