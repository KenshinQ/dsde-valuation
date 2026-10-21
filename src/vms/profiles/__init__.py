"""Economic-profile classifier (VMS-0.2 Phase 2, SPEC §7).

Interpretable rule-based classification with diagnostics. Does not run valuation
methods and does not claim investment alpha.
"""

from vms.profiles.classifier import CLASSIFIER_VERSION, classify_profile
from vms.profiles.features import ProfileFeatureBundle
from vms.profiles.overrides import ManualOverride, load_overrides
from vms.profiles.report import ProfileReport

__all__ = [
    "CLASSIFIER_VERSION",
    "ProfileFeatureBundle",
    "ProfileReport",
    "ManualOverride",
    "classify_profile",
    "load_overrides",
]
