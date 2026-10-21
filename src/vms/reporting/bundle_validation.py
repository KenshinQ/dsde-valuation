"""Result-bundle validation against SPEC §16.3 (VMS-0.2 Phase 12).

Phase CLIs emit *subsets* of the full §16.3 tree. This module:
- lists the canonical minimum artifact set;
- documents which CLI produces which subset;
- validates a directory for a named subset or a full release run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION

# SPEC §16.3 minimum artifact set (paths relative to run dir).
SECTION_16_3_MINIMUM: tuple[str, ...] = (
    "request.json",
    "config_snapshot.json",
    "data_manifest.json",
    "data_quality_report.json",
    "profile_report.json",
    "fundamental_state_posterior.json",
    "driver_diagnostics.json",
    "financial_path_summary.json",
    "method_eligibility.json",
    "method_results/",  # directory (or method_results.json flat alternative)
    "method_comparison.json",
    "ensemble_report.json",
    "market_pricing_report.json",
    "exit_price_summary.json",
    "return_distribution_summary.json",
    "sensitivity_report.json",
    "evaluation_report.json",
    "simulation_metadata.json",
    "validation_report.json",
)

# Flat alternatives accepted when a phase consolidates method_results/*.json
_METHOD_RESULTS_ALTS: tuple[str, ...] = ("method_results/", "method_results.json")

# Which artifacts each phase CLI is expected to produce (honest subset).
# Keys are CLI command names. Values are required relative paths / markers.
PHASE_CLI_SUBSETS: dict[str, tuple[str, ...]] = {
    "phase0": (
        "request.json",
        "config_snapshot.json",
        "data_manifest.json",
        "method_eligibility.json",
        "simulation_metadata.json",
    ),
    "phase3": (
        "config_snapshot.json",
        "simulation_bundle.json",
        "financial_path_bundle.json",
        "state_posterior.json",
        "simulation_metadata.json",
    ),
    "phase4": (
        "config_snapshot.json",
        "profile_report.json",
        "method_results.json",
        "simulation_metadata.json",
    ),
    "phase5": (
        "config_snapshot.json",
        "profile_report.json",
        "route_report.json",
        "peer_diagnostics.json",
        "method_results.json",
        "simulation_metadata.json",
    ),
    "phase6": (
        "config_snapshot.json",
        "profile_report.json",
        "method_results.json",
        "simulation_metadata.json",
    ),
    "phase7": (
        "method_eligibility.json",
        "method_comparison.json",
        "simulation_metadata.json",
    ),
    "phase8": (
        "ensemble_report.json",
        "simulation_metadata.json",
    ),
    "phase9": (
        "market_pricing_report.json",
        "exit_price_summary.json",
        "simulation_metadata.json",
    ),
    "phase10": (
        "exit_price_summary.json",
        "return_distribution_summary.json",
        "simulation_metadata.json",
    ),
    "phase11": (
        "evaluation_report.json",
        "sensitivity_report.json",
        "simulation_metadata.json",
    ),
    # Phase 12 release example: full Track A+B for mature; pattern-specific otherwise.
    "phase12": (
        "profile_report.json",
        "method_eligibility.json",
        "simulation_metadata.json",
        "validation_report.json",
        "phase12_summary.json",
    ),
    "phase12_mature_full": (
        "profile_report.json",
        "method_eligibility.json",
        "method_results.json",
        "market_pricing_report.json",
        "exit_price_summary.json",
        "return_distribution_summary.json",
        "simulation_metadata.json",
        "validation_report.json",
        "phase12_summary.json",
    ),
}

FORBIDDEN_ALPHA_SUBSTRINGS: tuple[str, ...] = (
    "INVESTMENT_VALUE_SUPPORTED",
    "guaranteed alpha",
    "guaranteed profit",
    "will outperform",
    "risk-free return",
)


@dataclass
class BundleValidationResult:
    ok: bool
    subset: str
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    extras_noted: list[str] = field(default_factory=list)
    schema_version: str | None = None
    implemented_phase: str | None = None
    investment_label: str | None = None
    alpha_claim_violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "subset": self.subset,
            "present": list(self.present),
            "missing": list(self.missing),
            "extras_noted": list(self.extras_noted),
            "schema_version": self.schema_version,
            "implemented_phase": self.implemented_phase,
            "investment_label": self.investment_label,
            "alpha_claim_violations": list(self.alpha_claim_violations),
            "notes": list(self.notes),
            "section_16_3_minimum": list(SECTION_16_3_MINIMUM),
            "validator_schema_version": SCHEMA_VERSION,
            "validator_implemented_phase": IMPLEMENTED_PHASE,
        }


def _exists(root: Path, rel: str) -> bool:
    p = root / rel
    if rel.endswith("/"):
        return p.is_dir() and any(p.iterdir())
    if rel == "method_results/":
        return p.is_dir() and any(p.iterdir())
    return p.is_file()


def _resolve_required(items: Iterable[str]) -> list[str]:
    """Expand method_results/ to accept flat method_results.json as well."""
    out: list[str] = []
    for it in items:
        if it in ("method_results/", "method_results.json"):
            if "method_results/" not in out:
                out.append("method_results/")
        else:
            out.append(it)
    return out


def _present_method_results(root: Path) -> bool:
    return any(_exists(root, a) for a in _METHOD_RESULTS_ALTS)


def validate_result_bundle(
    root: str | Path,
    *,
    subset: str = "phase12",
    require_investment_not_established: bool = True,
    scan_alpha_claims: bool = True,
) -> BundleValidationResult:
    """Validate ``root`` against a named PHASE_CLI_SUBSETS key or ``section_16_3``."""
    root = Path(root)
    result = BundleValidationResult(ok=False, subset=subset)
    if not root.is_dir():
        result.missing.append("<root>")
        result.notes.append(f"not a directory: {root}")
        return result

    if subset == "section_16_3":
        required = list(SECTION_16_3_MINIMUM)
    elif subset in PHASE_CLI_SUBSETS:
        required = list(PHASE_CLI_SUBSETS[subset])
    else:
        result.notes.append(f"unknown subset {subset!r}; known={sorted(PHASE_CLI_SUBSETS)}")
        return result

    for rel in required:
        if rel in ("method_results/", "method_results.json"):
            if _present_method_results(root):
                result.present.append("method_results")
            else:
                result.missing.append("method_results")
            continue
        if _exists(root, rel):
            result.present.append(rel.rstrip("/"))
        else:
            result.missing.append(rel.rstrip("/"))

    # Pull schema / labels from summary-ish files when present
    for candidate in (
        "phase12_summary.json",
        "phase11_summary.json",
        "phase10_summary.json",
        "simulation_metadata.json",
        "validation_report.json",
    ):
        p = root / candidate
        if not p.is_file():
            continue
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result.notes.append(f"{candidate}: invalid JSON")
            continue
        if isinstance(body, Mapping):
            result.schema_version = result.schema_version or body.get("schema_version")
            result.implemented_phase = result.implemented_phase or body.get("implemented_phase")
            iv = body.get("investment_value") or (body.get("labels") or {}).get("investment_value")
            if iv:
                result.investment_label = str(iv)
            # nested labels dict with boolean gate
            labels = body.get("labels")
            if isinstance(labels, Mapping) and labels.get("INVESTMENT_VALUE_NOT_ESTABLISHED") is True:
                result.investment_label = result.investment_label or "INVESTMENT_VALUE_NOT_ESTABLISHED"

    if require_investment_not_established:
        if result.investment_label and result.investment_label != "INVESTMENT_VALUE_NOT_ESTABLISHED":
            result.alpha_claim_violations.append(
                f"investment_value={result.investment_label!r} (expected INVESTMENT_VALUE_NOT_ESTABLISHED)"
            )
        # Also fail closed if a summary asserts SUPPORTED
        for p in root.rglob("*.json"):
            if p.stat().st_size > 2_000_000:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if '"INVESTMENT_VALUE_SUPPORTED"' in text or "'INVESTMENT_VALUE_SUPPORTED'" in text:
                # Allow mention inside documentation of forbidden statuses / release_gates keys
                if '"INVESTMENT_VALUE_SUPPORTED": true' in text or '"INVESTMENT_VALUE_SUPPORTED":true' in text:
                    result.alpha_claim_violations.append(f"{p.relative_to(root)}: INVESTMENT_VALUE_SUPPORTED=true")

    if scan_alpha_claims:
        for p in list(root.glob("*.md")) + list(root.glob("*.txt")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            for needle in FORBIDDEN_ALPHA_SUBSTRINGS:
                if needle.lower() in text and needle != "INVESTMENT_VALUE_SUPPORTED":
                    result.alpha_claim_violations.append(f"{p.name}: contains {needle!r}")

    result.ok = not result.missing and not result.alpha_claim_violations
    if subset == "section_16_3" and result.missing:
        result.notes.append(
            "Full §16.3 is the aspirational run tree; phase CLIs emit documented subsets "
            "(see PHASE_CLI_SUBSETS / docs/architecture.md)."
        )
    return result


def write_validation_report(root: str | Path, *, subset: str = "phase12") -> dict[str, Any]:
    """Validate and write ``validation_report.json`` into ``root``."""
    root = Path(root)
    res = validate_result_bundle(root, subset=subset)
    payload = res.to_dict()
    payload["status"] = "PASS" if res.ok else "FAIL"
    (root / "validation_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload
