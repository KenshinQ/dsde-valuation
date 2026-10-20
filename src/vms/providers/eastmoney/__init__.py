"""Eastmoney public datacenter / F10 enrichment for VMS (CA, shares, industry).

Assumptions: EM-CA-SHAREBONUS-v1, EM-SHARES-EQUITY-v1, INDUSTRY-SW-L1-PROXY-EM-v1
(see docs/assumptions.md). Never invent announced_at from ex_date.
"""

from vms.providers.eastmoney.enrich import EnrichmentResult, enrich_bundle

__all__ = ["enrich_bundle", "EnrichmentResult"]
