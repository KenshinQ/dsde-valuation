"""Phase 4 cash-flow valuation methods (SPEC §12.1–12.3, §20 Phase 4).

Plugins: ``fcff_dcf``, ``fcfe_dcf``, ``ddm``. Each must pass hard eligibility
gates before computing. No averaging / ensemble (Phase 8). Engineering ≠ alpha.
"""

from vms.methods.cash_flow.ddm_plugin import DdmMethod
from vms.methods.cash_flow.equity_dcf import (
    DDMResult,
    EquityDCFResult,
    dcf_fcfe,
    ddm_equity,
    payout_modelable,
)
from vms.methods.cash_flow.fcfe_plugin import FcfeDcfMethod
from vms.methods.cash_flow.fcff_plugin import FcffDcfMethod
from vms.methods.cash_flow.run import MethodRunBundle, run_eligible_cashflow_methods

__all__ = [
    "FcffDcfMethod",
    "FcfeDcfMethod",
    "DdmMethod",
    "EquityDCFResult",
    "DDMResult",
    "dcf_fcfe",
    "ddm_equity",
    "payout_modelable",
    "MethodRunBundle",
    "run_eligible_cashflow_methods",
]
