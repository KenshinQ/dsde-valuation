"""Financial statement projection.

VMS-0.2 Phase 3: deterministic central case (generic operating company).
VMS-0.2 Phase 3 path-wise: path-wise projection of SimulationBundle (PATH-STATEMENTS-v1).

Importing this package registers the built-in sector profiles.
"""

from vms.statements import projection as _projection  # noqa: F401  (registers OperatingCompanyProfile)
from vms.statements.paths import (CentralPathError, FinancialPathBundle, FinancialPathRecord,
                                  project_financial_paths)

__all__ = ["CentralPathError", "FinancialPathBundle", "FinancialPathRecord", "project_financial_paths"]
