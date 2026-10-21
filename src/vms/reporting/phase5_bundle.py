"""VMS-0.2 Phase 5 offline relative-multiples demo (SPEC §20 Phase 5).

Synthetic mature-operating subject + PIT peer multiples → pe/pb/ev_* via router.
Keeps Phase 4 cash-flow methods available in the same artifact set when paths run.
No RIM/NAV/SOTP, no ensemble, no exit-price estimator.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.data import synthetic
from vms.data.io import load_directory, write_directory
from vms.market_pricing import unavailable_market_pricing
from vms.methods import build_registry_from_config
from vms.methods.cash_flow import run_eligible_cashflow_methods
from vms.methods.multiples import run_eligible_multiple_methods
from vms.pipeline import run_path_projection
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.reporting.metadata import ArtifactStamp, content_run_id, hash_models, sha256_of, write_artifact
from vms.schemas.config import load_config
from vms.schemas.contracts import ValuationTarget
from vms.schemas.observations import PeerObservation, QualityStatus

PHASE5_STATUS = "PHASE5_RELATIVE_MULTIPLES_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = "INVESTMENT_VALUE_NOT_ESTABLISHED"
CST = timezone(timedelta(hours=8))


class Phase5BundleError(ValueError):
    pass


def _profile_for_synthetic(as_of_iso: str) -> tuple[Any, frozenset[str]]:
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data)
    feats = feats.model_copy(update={
        "instrument_id": synthetic.SYNTHETIC_INSTRUMENT,
        "as_of": as_of_iso[:10] if "T" not in as_of_iso else as_of_iso[:10],
    })
    return classify_profile(feats), frozenset(data.get("available_fields") or [])


def _synthetic_peers(subject_id: str, as_of: datetime) -> list[PeerObservation]:
    """Hand-built PIT peer multiples known at as_of (plus one future leaker for exclusion)."""
    pub = datetime(2022, 1, 15, 9, tzinfo=CST)
    metric_ts = datetime(2024, 12, 30, 15, tzinfo=CST)
    if metric_ts > as_of:
        metric_ts = as_of
    rows: list[PeerObservation] = []
    # Diverse positive multiples for each metric family
    tables = {
        "pe": [12.0, 14.0, 15.5, 13.0, 16.0, 11.5, 18.0, 14.5],
        "pb": [1.8, 2.1, 2.4, 1.9, 2.0, 2.2, 1.7, 2.3],
        "ev_ebit": [10.0, 11.5, 12.0, 9.5, 13.0, 10.5, 11.0, 12.5],
        "ev_ebitda": [8.0, 8.5, 9.0, 7.5, 9.5, 8.2, 8.8, 9.2],
        "ev_sales": [2.0, 2.2, 2.5, 1.8, 2.4, 2.1, 2.3, 1.9],
    }
    for metric, vals in tables.items():
        for i, v in enumerate(vals):
            rows.append(PeerObservation(
                subject_instrument_id=subject_id,
                peer_instrument_id=f"PEER{i:02d}.SZ",
                published_at=pub,
                membership_start=date(2021, 1, 1),
                membership_end=None,
                field_name=metric,
                value=float(v),
                currency="CNY",
                unit_scale="unit",
                metric_timestamp=metric_ts,
                source_id="SYNTHETIC",
                revision_id="r0",
                quality_status=QualityStatus.OBSERVED,
            ))
    # Future reconstitution / metric — must be excluded by PIT gate
    rows.append(PeerObservation(
        subject_instrument_id=subject_id,
        peer_instrument_id="FUTURE99.SZ",
        published_at=datetime(2026, 1, 1, 9, tzinfo=CST),
        membership_start=date(2025, 1, 1),
        field_name="pe",
        value=99.0,
        currency="CNY",
        unit_scale="unit",
        metric_timestamp=datetime(2026, 1, 2, 15, tzinfo=CST),
        source_id="SYNTHETIC",
        revision_id="r0",
        quality_status=QualityStatus.OBSERVED,
    ))
    # Negative peer multiple — excluded at aggregation / peer set
    rows.append(PeerObservation(
        subject_instrument_id=subject_id,
        peer_instrument_id="NEG01.SZ",
        published_at=pub,
        membership_start=date(2021, 1, 1),
        field_name="pe",
        value=-5.0,
        currency="CNY",
        unit_scale="unit",
        metric_timestamp=metric_ts,
        source_id="SYNTHETIC",
        revision_id="r0",
        quality_status=QualityStatus.OBSERVED,
    ))
    return rows


def _subject_metrics_from_synthetic() -> dict[str, float]:
    # Hand numbers aligned with mature operating fixture economics (not a real quote).
    return {
        "parent_net_income": 100.0,
        "total_equity": 500.0,
        "ebit": 140.0,
        "depreciation_amortization": 20.0,
        "ebitda": 160.0,
        "revenue": 1000.0,
        "cash": 50.0,
        "interest_bearing_debt": 120.0,
        "diluted_shares": 10.0,
        "lease_debt_like": 0.0,
        "minority_interest_book": 0.0,
        "other_senior_claims": 0.0,
    }


def build_phase5_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path,
    seed: int = 42,
    paths: int = 20,
    years: int = 3,
    as_of: datetime | None = None,
    policy_id: str | None = None,
    data_format: str = "csv",
    target: ValuationTarget = ValuationTarget.RELATIVE_VALUE_CURRENT,
    include_cashflow: bool = True,
) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    loaded = load_config(config_path)
    cfg = loaded.config
    if as_of is None:
        as_of, as_of_note = parse_as_of("2025-06-30")
    else:
        as_of_note = AS_OF_DATE_RULE
    if paths <= 0:
        raise Phase5BundleError(f"paths must be > 0 (got {paths})")

    data_dir = out / "data"
    fin, mkt, actions = synthetic.generate(seed)
    peers = _synthetic_peers(synthetic.SYNTHETIC_INSTRUMENT, as_of)
    write_directory(
        data_dir, fin, mkt, actions, synthetic.source_descriptors(), fmt=data_format,
        classifications=synthetic.classifications(), peers=peers,
    )
    load = load_directory(data_dir)

    profile, available_fields = _profile_for_synthetic(as_of.isoformat())
    # Multiples need fields for eligibility
    available_fields = frozenset(set(available_fields) | {
        "parent_net_income", "total_equity", "ebit", "depreciation_amortization",
        "revenue", "interest_bearing_debt", "cash",
    })
    registry = build_registry_from_config(loaded.method_registry)
    subject_metrics = _subject_metrics_from_synthetic()

    multiples_run = run_eligible_multiple_methods(
        registry=registry,
        profile=profile,
        target=target,
        loaded=loaded,
        available_fields=available_fields,
        subject_metrics=subject_metrics,
        peer_observations=list(load.peers),
        as_of=as_of.isoformat(),
    )

    cashflow_results: list[Any] = []
    cashflow_eligible: list[str] = []
    financial_n_valid = None
    if include_cashflow:
        run = run_path_projection(
            load, instrument_id=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of, loaded=loaded,
            seed=seed, n_paths=paths, n_years=years, policy_id=policy_id,
        )
        if run.financial_paths is not None:
            financial_n_valid = run.financial_paths.n_valid
            cf = run_eligible_cashflow_methods(
                registry=registry,
                profile=profile,
                target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
                financial_paths=run.financial_paths,
                loaded=loaded,
                available_fields=available_fields,
            )
            cashflow_results = list(cf.results)
            cashflow_eligible = list(cf.eligible_run)

    data_hash = sha256_of({
        "records": hash_models([
            *load.financial, *load.market, *load.corporate_actions, *load.classifications, *load.peers,
        ]),
        "sources": {k: v.model_dump(mode="json") for k, v in sorted(load.sources.items())},
    })
    config_snapshot = {
        "config": cfg.model_dump(mode="json"),
        "driver_profile": loaded.profile.model_dump(mode="json"),
        "method_registry_version": loaded.method_registry.registry_version,
    }
    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase5", instrument=synthetic.SYNTHETIC_INSTRUMENT, as_of=as_of.isoformat(),
            seed=seed, paths=paths, years=years, data=data_hash,
            config=sha256_of(config_snapshot), policy=policy_id, target=target.value,
        ),
    )

    write_artifact(out, "config_snapshot.json", config_snapshot, stamp)
    write_artifact(out, "data_manifest.json", {
        "instrument_id": synthetic.SYNTHETIC_INSTRUMENT,
        "as_of": as_of.isoformat(),
        "as_of_interpretation": as_of_note,
        "data_label": "SYNTHETIC — not real market data",
        "n_financial": len(load.financial),
        "n_peers": len(load.peers),
        "data_hash": data_hash,
    }, stamp)
    write_artifact(out, "profile_report.json", profile.model_dump(mode="json"), stamp)
    write_artifact(out, "route_report.json", multiples_run.route.model_dump(mode="json"), stamp)
    write_artifact(out, "peer_diagnostics.json", multiples_run.peer_diagnostics, stamp)
    write_artifact(out, "method_results.json", {
        "results": [r.model_dump(mode="json") for r in (*cashflow_results, *multiples_run.results)],
        "eligible_run": [*cashflow_eligible, *multiples_run.eligible_run],
        "skipped": multiples_run.skipped,
        "ensemble": None,
        "notes": multiples_run.notes,
        "investment_value": INVESTMENT_LABEL,
        "subject_metrics": subject_metrics,
    }, stamp)

    mp = unavailable_market_pricing()
    write_artifact(out, "simulation_metadata.json", {
        "status": PHASE5_STATUS,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "warning": (
            "Phase 5 relative multiples (P/E, P/B, EV/*) + optional Phase 4 cash-flow. "
            "No RIM/NAV/SOTP, no calibrated ensemble, no exit-price estimator. "
            "Not investment advice."
        ),
        "data_label": "SYNTHETIC — not real market data",
        "seed": seed,
        "n_paths": paths,
        "n_years": years,
        "financial_n_valid": financial_n_valid,
        "eligible_run": [*cashflow_eligible, *multiples_run.eligible_run],
        "market_pricing_status": mp.status,
        "created_at": datetime.now(ZoneInfo(cfg.timezone)).isoformat(),
    }, stamp)

    summary = {
        "status": PHASE5_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "paths": paths,
        "years": years,
        "target": target.value,
        "profile_primary": profile.primary_profile.value,
        "coverage_status": multiples_run.route.coverage_status,
        "eligible_run": [*cashflow_eligible, *multiples_run.eligible_run],
        "method_statuses": [
            {"method_id": r.method_id, "status": r.status.value, "reason_codes": r.reason_codes}
            for r in (*cashflow_results, *multiples_run.results)
        ],
        "financial_n_valid": financial_n_valid,
        "market_pricing_status": mp.status,
        "ensemble": None,
        "peer_methods_with_diagnostics": sorted(multiples_run.peer_diagnostics),
        "data_hash": data_hash[:16],
    }
    (out / "phase5_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"
