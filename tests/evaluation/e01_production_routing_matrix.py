"""Official VTP-0.1 E-01 production routing matrix (10×12×4).

Calls production ``vms.router.route_methods`` only. Never uses a simplified
or toy router. Comparison policy is declared here *before* results are used
to change fixtures or expected routes.

Agreed axes
-----------
- 10 VTP §4.2 companies: SYN-MATURE, SYN-GROWTH, SYN-BANK, SYN-CYCLICAL,
  SYN-ASSET, SYN-HOLDCO, SYN-DISTRESSED, SYN-HYBRID, SYN-BAD-DATA, SYN-NO-PEERS
- 12 methods: 11 production registry ids plus MIDCYCLE_NORMALIZED (named in the
  historical 10×12×4 axis and YAML, but **not** in the production registry)
- 4 official E-01/E-03 targets: FUNDAMENTAL_VALUE_CURRENT, MARKET_EXIT_PRICE,
  ASSET_NAV, TOTAL_RETURN

Predeclared expected sources (frozen, not tuned after this run)
---------------------------------------------------------------
- Method-level expected_routes in tests/vtp_0_1/fixtures/synthetic_companies.yaml
  exist only on some evidence branches; when absent, this module also accepts a
  bundled copy under tests/evaluation/fixtures/e01_routing/expected_routes.yaml
  which must be a verbatim extract of that frozen YAML (do not retune).
- Target expansion rule (from official E-03 / registry supported_targets, not
  from observing a run): a method-level expected status applies only on targets
  the method declares. On other official targets the expanded expected is
  UNSUPPORTED.
- Methods not mentioned for a company remain NOT_PREDECLARED (unknown expected).
- SYN-BAD-DATA ``ALL_METHODS: BLOCKED`` expands to INELIGIBLE on supported
  targets and UNSUPPORTED on unsupported targets.
- YAML WARN / CONDITIONAL cannot strictly match production MethodEligibilityStatus
  (VALID / INELIGIBLE only). Those cells are EXPECTED_NON_BINARY, not MATCH.

Vacuous / structural cells (must not inflate a PASS rate)
---------------------------------------------------------
- MIDCYCLE_NORMALIZED: METHOD_NOT_IN_REGISTRY for every company×target
- TOTAL_RETURN: no production method declares this target (structural UNSUPPORTED)
- Peer count 0 is *deferred* at eligibility (PEER_COUNT_HINT passed); E-05 hard
  reject of relative methods is not claimed at this route_methods layer

E-01 cannot be PASS while any NOT_PREDECLARED, EXPECTED_NON_BINARY, MISMATCH,
or METHOD_NOT_IN_REGISTRY cell remains, or while TOTAL_RETURN is structurally
unsupported across the registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml

from vms.methods import build_registry_from_config
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.router import route_methods
from vms.router.route import RouteReport
from vms.schemas.config import load_config
from vms.schemas.contracts import ValuationTarget

REPO = Path(__file__).resolve().parents[2]
EVAL_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e01_routing"

COMPANIES = (
    "SYN-MATURE",
    "SYN-GROWTH",
    "SYN-BANK",
    "SYN-CYCLICAL",
    "SYN-ASSET",
    "SYN-HOLDCO",
    "SYN-DISTRESSED",
    "SYN-HYBRID",
    "SYN-BAD-DATA",
    "SYN-NO-PEERS",
)

# Historical 10×12×4 method axis. The last id is not in production.
MATRIX_METHODS = (
    "fcff_dcf",
    "fcfe_dcf",
    "ddm",
    "residual_income",
    "pe",
    "pb",
    "ev_ebit",
    "ev_ebitda",
    "ev_sales",
    "nav",
    "sotp",
    "midcycle_normalized",
)

OFFICIAL_TARGETS = (
    ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
    ValuationTarget.MARKET_EXIT_PRICE,
    ValuationTarget.ASSET_NAV,
    ValuationTarget.TOTAL_RETURN,
)

YAML_METHOD_TO_ID = {
    "FCFF_DCF": "fcff_dcf",
    "FCFE_DCF": "fcfe_dcf",
    "DDM": "ddm",
    "RIM": "residual_income",
    "PE_MULTIPLE": "pe",
    "PB_MULTIPLE": "pb",
    "EV_EBIT": "ev_ebit",
    "EV_EBITDA": "ev_ebitda",
    "EV_SALES": "ev_sales",
    "NAV": "nav",
    "SOTP": "sotp",
    "MIDCYCLE_NORMALIZED": "midcycle_normalized",
    "RECOVERY_METHOD": "recovery_method",
}

ID_TO_YAML = {v: k for k, v in YAML_METHOD_TO_ID.items()}

COMPANY_SPEC = {
    "SYN-MATURE": {
        "fixture": fixtures_dir() / "mature_operating.json",
        "peer_count": 0,
        "data_quality_blocked": False,
    },
    "SYN-GROWTH": {
        "fixture": fixtures_dir() / "growth_negative_fcf.json",
        "peer_count": 0,
        "data_quality_blocked": False,
    },
    "SYN-BANK": {
        "fixture": fixtures_dir() / "financial_institution.json",
        "peer_count": 0,
        "data_quality_blocked": False,
    },
    "SYN-CYCLICAL": {
        "fixture": fixtures_dir() / "cyclical.json",
        "peer_count": 0,
        "data_quality_blocked": False,
    },
    "SYN-HOLDCO": {
        "fixture": fixtures_dir() / "holding.json",
        "peer_count": 0,
        "data_quality_blocked": False,
    },
    "SYN-ASSET": {
        "fixture": EVAL_FIXTURES / "syn_asset.json",
        "peer_count": 0,
        "data_quality_blocked": False,
    },
    "SYN-DISTRESSED": {
        "fixture": EVAL_FIXTURES / "syn_distressed.json",
        "peer_count": 0,
        "data_quality_blocked": False,
    },
    "SYN-HYBRID": {
        "fixture": EVAL_FIXTURES / "syn_hybrid.json",
        "peer_count": 0,
        "data_quality_blocked": False,
    },
    "SYN-BAD-DATA": {
        "fixture": EVAL_FIXTURES / "syn_bad_data.json",
        "peer_count": 0,
        "data_quality_blocked": True,
    },
    "SYN-NO-PEERS": {
        "fixture": fixtures_dir() / "mature_operating.json",
        "peer_count": 0,
        "data_quality_blocked": False,
        "note": "Same economic fixture as SYN-MATURE; peer_count=0 is the designed condition.",
    },
}


def _load_expected_yaml() -> dict[str, Any]:
    """Load frozen method-level expected routes. Prefer the repo YAML if present."""
    candidates = [
        REPO / "tests" / "vtp_0_1" / "fixtures" / "synthetic_companies.yaml",
        EVAL_FIXTURES / "expected_routes.yaml",
    ]
    for path in candidates:
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return {"path": str(path), "companies": data.get("companies") or {}}
    raise FileNotFoundError("frozen expected_routes YAML not found")


def method_supported_targets(registry) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for e in registry._config.methods if hasattr(registry, "_config") else []:
        out[e.method_id] = {t.value for t in e.supported_targets}
    if out:
        return out
    # Fallback: inspect entries via for_target over all enum values
    for e in getattr(registry, "methods", []) or []:
        out[e.method_id] = {t.value for t in e.supported_targets}
    if not out:
        from vms.schemas.config import load_config
        loaded = load_config(REPO / "config" / "default.yaml")
        for e in loaded.method_registry.methods:
            out[e.method_id] = {t.value for t in e.supported_targets}
    return out


def expanded_expected(
    *,
    company_id: str,
    method_id: str,
    target: str,
    supported: dict[str, set[str]],
    yaml_companies: dict[str, Any],
) -> tuple[str, str]:
    """Return (expected_status, expected_source)."""
    in_registry = method_id in supported
    if not in_registry:
        # Still record YAML if present, but actual will be NOT_IN_REGISTRY
        routes = (yaml_companies.get(company_id) or {}).get("expected_routes") or {}
        yaml_name = ID_TO_YAML.get(method_id, method_id.upper())
        if yaml_name in routes and isinstance(routes[yaml_name], str):
            return routes[yaml_name], "yaml_method_level_but_method_not_in_registry"
        return "NOT_IN_REGISTRY", "method_absent_from_production_registry"

    if target not in supported[method_id]:
        return "UNSUPPORTED", "e03_target_not_in_method_supported_targets"

    routes = (yaml_companies.get(company_id) or {}).get("expected_routes") or {}
    if routes.get("ALL_METHODS") == "BLOCKED":
        return "INELIGIBLE", "yaml_all_methods_blocked"

    yaml_name = ID_TO_YAML.get(method_id)
    raw = routes.get(yaml_name) if yaml_name else None
    if isinstance(raw, str) and raw in {"ELIGIBLE", "INELIGIBLE", "WARN", "CONDITIONAL", "BLOCKED"}:
        if raw == "BLOCKED":
            return "INELIGIBLE", "yaml_method_level_blocked"
        return raw, "yaml_method_level_on_supported_target"
    return "NOT_PREDECLARED", "no_method_level_expected_in_frozen_yaml"


def actual_from_report(
    *,
    method_id: str,
    target: str,
    supported: dict[str, set[str]],
    report: RouteReport | None,
) -> tuple[str, list[dict[str, Any]], str]:
    """Return (actual_status, reason_payload, layer_note)."""
    if method_id not in supported:
        return "NOT_IN_REGISTRY", [], "method_absent_from_production_registry"
    if target not in supported[method_id]:
        return "UNSUPPORTED", [{"code": "TARGET_NOT_IN_REGISTRY_SUPPORTED_TARGETS", "passed": False, "detail": f"target={target}"}], "for_target_excludes_method"
    assert report is not None
    for elig in report.eligibility:
        if elig.method_id == method_id:
            reasons = [
                {"code": r.code, "passed": r.passed, "detail": r.detail}
                for r in elig.reasons
            ]
            status = "ELIGIBLE" if elig.eligible else "INELIGIBLE"
            return status, reasons, "route_methods.eligibility"
    # Considered list should include every for_target method
    return "NOT_IN_REPORT", [], "method_supported_but_missing_from_route_report"


def classify_cell(expected: str, actual: str) -> str:
    if actual == "NOT_IN_REGISTRY":
        return "METHOD_NOT_IN_REGISTRY"
    if expected == "NOT_PREDECLARED":
        return "NOT_PREDECLARED"
    if expected in {"WARN", "CONDITIONAL"}:
        return "EXPECTED_NON_BINARY"
    if expected == "UNSUPPORTED" and actual == "UNSUPPORTED":
        return "STRUCTURAL_UNSUPPORTED"
    if expected == "ELIGIBLE" and actual == "ELIGIBLE":
        return "MATCH"
    if expected in {"INELIGIBLE", "BLOCKED"} and actual == "INELIGIBLE":
        return "MATCH"
    return "MISMATCH"


def official_e01_status(summary: dict[str, Any]) -> str:
    """Fail-closed official E-01 label. Never PASS with gaps."""
    if (
        summary.get("mismatches", 0) > 0
        or summary.get("not_predeclared", 0) > 0
        or summary.get("expected_non_binary", 0) > 0
        or summary.get("method_not_in_registry", 0) > 0
        or summary.get("structural_unsupported_total_return", 0) > 0
        or summary.get("not_executed", 0) > 0
    ):
        # Execution of the production API may still be complete.
        if summary.get("executed_route_calls", 0) > 0 and summary.get("not_executed", 0) == 0:
            return "PARTIAL"
        return "BLOCKED"
    return "PASS"


def build_matrix(*, seed_note: str = "") -> dict[str, Any]:
    expected_pack = _load_expected_yaml()
    yaml_companies = expected_pack["companies"]
    loaded = load_config(REPO / "config" / "default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    supported = method_supported_targets(registry)
    production_methods = sorted(supported)
    structural_total_return = all(
        "TOTAL_RETURN" not in tg for tg in supported.values()
    )

    cells: list[dict[str, Any]] = []
    reports: dict[str, dict[str, Any]] = {}
    profile_reports: dict[str, dict[str, Any]] = {}

    tz = timezone(timedelta(hours=8))
    started = datetime.now(tz).isoformat(timespec="seconds")

    for company_id in COMPANIES:
        spec = COMPANY_SPEC[company_id]
        fixture_path: Path = spec["fixture"]
        data = load_fixture(fixture_path)
        if spec.get("data_quality_blocked") and data.get("data_quality_blocked") is False:
            pass
        features = features_from_fixture(data)
        profile = classify_profile(features)
        available = frozenset(data.get("available_fields") or [])
        dq = bool(spec["data_quality_blocked"] or data.get("data_quality_blocked"))
        peer_count = int(spec["peer_count"])
        profile_reports[company_id] = {
            **profile.model_dump(mode="json"),
            "fixture_path": str(fixture_path),
            "peer_count": peer_count,
            "data_quality_blocked": dq,
            "available_fields": sorted(available),
        }
        reports[company_id] = {}
        for target in OFFICIAL_TARGETS:
            report = route_methods(
                registry=registry,
                profile=profile,
                target=target,
                available_fields=available,
                peer_count=peer_count,
                data_quality_blocked=dq,
                attempt_value_paths=False,
            )
            if not isinstance(report, RouteReport):
                raise TypeError("route_methods did not return RouteReport")
            reports[company_id][target.value] = {
                "instrument_id": report.instrument_id,
                "profile_primary": report.profile_primary,
                "profile_low_confidence": report.profile_low_confidence,
                "coverage_status": report.coverage_status,
                "candidates": list(report.candidates),
                "eligible": [e.method_id for e in report.eligibility if e.eligible],
                "ineligible": [e.method_id for e in report.eligibility if not e.eligible],
                "routing_deterministic": report.routing_deterministic,
                "investment_value": report.investment_value,
                "api": "vms.router.route_methods",
            }
            for method_id in MATRIX_METHODS:
                exp, exp_src = expanded_expected(
                    company_id=company_id,
                    method_id=method_id,
                    target=target.value,
                    supported=supported,
                    yaml_companies=yaml_companies,
                )
                actual, reasons, layer = actual_from_report(
                    method_id=method_id,
                    target=target.value,
                    supported=supported,
                    report=report if method_id in supported and target.value in supported.get(method_id, set()) else None,
                )
                outcome = classify_cell(exp, actual)
                vacuous = outcome in {
                    "STRUCTURAL_UNSUPPORTED",
                    "METHOD_NOT_IN_REGISTRY",
                    "NOT_PREDECLARED",
                    "EXPECTED_NON_BINARY",
                }
                if target == ValuationTarget.TOTAL_RETURN and actual == "UNSUPPORTED":
                    vacuous = True
                    if outcome == "STRUCTURAL_UNSUPPORTED":
                        pass
                cells.append({
                    "company_id": company_id,
                    "method_id": method_id,
                    "yaml_method": ID_TO_YAML.get(method_id),
                    "target": target.value,
                    "expected_status": exp,
                    "expected_source": exp_src,
                    "actual_status": actual,
                    "actual_layer": layer,
                    "reasons": reasons,
                    "comparison": outcome,
                    "vacuous": vacuous,
                    "peer_count": peer_count,
                    "data_quality_blocked": dq,
                    "profile_primary": report.profile_primary,
                    "profile_low_confidence": report.profile_low_confidence,
                })

    # Determinism: repeat SYN-MATURE × FUNDAMENTAL_VALUE_CURRENT
    det_ok = True
    det_detail = ""
    mature_spec = COMPANY_SPEC["SYN-MATURE"]
    data = load_fixture(mature_spec["fixture"])
    profile = classify_profile(features_from_fixture(data))
    r1 = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=frozenset(data.get("available_fields") or []),
        peer_count=0,
        data_quality_blocked=False,
    )
    r2 = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=frozenset(data.get("available_fields") or []),
        peer_count=0,
        data_quality_blocked=False,
    )
    a1 = [(e.method_id, e.eligible, [(r.code, r.passed) for r in e.reasons]) for e in r1.eligibility]
    a2 = [(e.method_id, e.eligible, [(r.code, r.passed) for r in e.reasons]) for e in r2.eligibility]
    det_ok = a1 == a2
    det_detail = "identical eligibility and reason codes on repeat call" if det_ok else "DIVERGED"

    counts: dict[str, int] = {}
    for c in cells:
        counts[c["comparison"]] = counts.get(c["comparison"], 0) + 1

    n_total = len(cells)
    n_tr = sum(1 for c in cells if c["target"] == "TOTAL_RETURN")
    non_vacuous = [c for c in cells if not c["vacuous"]]
    scored = [c for c in non_vacuous if c["comparison"] in {"MATCH", "MISMATCH"}]
    summary = {
        "total_cells": n_total,
        "expected_shape": f"{len(COMPANIES)}x{len(MATRIX_METHODS)}x{len(OFFICIAL_TARGETS)}={len(COMPANIES)*len(MATRIX_METHODS)*len(OFFICIAL_TARGETS)}",
        "matches": counts.get("MATCH", 0),
        "mismatches": counts.get("MISMATCH", 0),
        "not_predeclared": counts.get("NOT_PREDECLARED", 0),
        "expected_non_binary": counts.get("EXPECTED_NON_BINARY", 0),
        "method_not_in_registry": counts.get("METHOD_NOT_IN_REGISTRY", 0),
        "structural_unsupported": counts.get("STRUCTURAL_UNSUPPORTED", 0),
        "structural_unsupported_total_return": n_tr if structural_total_return else 0,
        "not_executed": 0,
        "executed_route_calls": len(COMPANIES) * len(OFFICIAL_TARGETS),
        "vacuous_cells": sum(1 for c in cells if c["vacuous"]),
        "non_vacuous_cells": len(non_vacuous),
        "scored_match_or_mismatch": len(scored),
        "production_methods_in_registry": production_methods,
        "no_production_method_supports_total_return": structural_total_return,
        "peer_gate_deferred_when_count_zero": True,
        "api": "vms.router.route_methods",
        "toy_router_used": False,
        "determinism_repeat_ok": det_ok,
        "determinism_detail": det_detail,
        "counts": counts,
    }
    summary["official_e01"] = official_e01_status(summary)

    return {
        "started_at_asia_shanghai": started,
        "finished_at_asia_shanghai": datetime.now(tz).isoformat(timespec="seconds"),
        "seed_note": seed_note,
        "api": "vms.router.route_methods",
        "attempt_value_paths": False,
        "expected_yaml": expected_pack["path"],
        "companies": list(COMPANIES),
        "methods": list(MATRIX_METHODS),
        "targets": [t.value for t in OFFICIAL_TARGETS],
        "production_method_supported_targets": {k: sorted(v) for k, v in supported.items()},
        "summary": summary,
        "profile_reports": profile_reports,
        "route_call_summaries": reports,
        "cells": cells,
    }


def write_artifacts(bundle: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_all=True) if False else out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "e01_production_routing_matrix.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # CSV
    import csv
    fields = [
        "company_id", "method_id", "yaml_method", "target", "expected_status",
        "expected_source", "actual_status", "comparison", "vacuous",
        "profile_primary", "profile_low_confidence", "peer_count",
        "data_quality_blocked", "actual_layer",
    ]
    with (out_dir / "e01_production_routing_matrix.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in bundle["cells"]:
            w.writerow(row)
    (out_dir / "e01_summary.json").write_text(
        json.dumps(bundle["summary"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    bundle = build_matrix()
    write_artifacts(bundle, args.out)
    print(json.dumps(bundle["summary"], ensure_ascii=False, indent=2))
