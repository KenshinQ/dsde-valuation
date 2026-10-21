# Phase 8 — Ensemble and model uncertainty: DONE (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE7_DONE.md](PHASE7_DONE.md).

Status: **all Phase 8 acceptance criteria pass** for compatibility-gated ensembles,
named weight protocols, distributional mixture, separate intrinsic vs market-outcome
weight artifacts, and leave-one-method-out / between-method disagreement on synthetic
examples. Label: `ENGINEERING_PASS` for Phase 8 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** investment advice and does **not** claim investment value.
**No** `ENSEMBLE_CALIBRATED` / `INVESTMENT_VALUE_SUPPORTED` without real OOS evidence.
Phases 9+ (market-pricing exit engine / returns rewrite / walk-forward) are **not** claimed done.

> Note: an older VMS-0.1 `PHASE8_DONE.md` (sensitivity & uncertainty attribution under 0.1
> numbering) is superseded by this VMS-0.2 Phase 8 report. The 0.1 sensitivity work remains in
> `vms.diagnostics` / CLI `vms sensitivity` and is covered by retained diagnostics suites.

## Changed / added files (VMS-0.2 Phase 8)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase8, PHASE_8
src/vms/ensemble/__init__.py                NEW: public exports
src/vms/ensemble/protocols.py               NEW: named/versioned WeightProtocol (§13.3–13.4)
src/vms/ensemble/weights.py                 NEW: WeightArtifact; ≥0 sum-to-1; intrinsic vs MARKET_OUTCOME
src/vms/ensemble/checklist.py               NEW: §13.3 checklist + CalibrationEvidence
src/vms/ensemble/mixture.py                 NEW: MethodDistribution + P(V)=Σ w_m P_m
src/vms/ensemble/disagreement.py            NEW: between-method + leave-one-method-out
src/vms/ensemble/build.py                   NEW: build_ensemble orchestration (prod refuse / PRIOR_ONLY)
src/vms/reporting/phase8_bundle.py          NEW: offline ensemble emitter
src/vms/cli/main.py                         `vms phase8`
src/vms/router/compatibility.py             notes → Phase 8 ensemble ownership
src/vms/router/compare.py / __init__.py     notes
config/*.yaml                               versions → phase8
tests/unit/test_phase8_acceptance.py        NEW (§20 AC1–AC6)
tests/property/test_ensemble_properties.py  NEW (§21.2 weights / ineligible)
tests/integration/test_cli_phase8.py        NEW
PHASE8_DONE.md / README.md / schema hardcodes
```

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **615 passed** (Phase 7 was **598**; +17) |
| CLI | `vms phase8 --out /tmp/vms_phase8_smoke --seed 42 --fixture mature --n-draws 400` | `PHASE8_ENSEMBLE_NOT_INVESTMENT_ADVICE`; production_mixture=false; research_mode=`PRIOR_ONLY`; calibrated_claim=false |

## Acceptance criterion → evidence (§20 Phase 8 / §24)

| # | Criterion (SPEC §20 Phase 8) | Evidence |
|---|---|---|
| 1 | Uncalibrated or incompatible methods cannot form a production ensemble | `build_ensemble(..., intent="production")` → mixture=None, `ENSEMBLE_UNCALIBRATED` / `CALIBRATION_INSUFFICIENT`; incompatible EV↔EQUITY → `NOT_COMBINED_INCOMPATIBLE`; `test_ac1_*` |
| 2 | Mixture weights are non-negative, sum to one, and carry a named target/scoring protocol | `WeightArtifact` + `WeightProtocol` (`protocol_id`/`protocol_version`/`target`/`scoring_rule`); `test_ac2_*`; property `test_normalized_weights_nonneg_sum_to_one` |
| 3 | No default equal-weight blend is exposed as calibrated | Research path labels `PRIOR_ONLY` / `ENSEMBLE_UNCALIBRATED`; never `ENSEMBLE_CALIBRATED`; `test_ac3_equal_weight_not_calibrated`; CLI `equal_weight_labeled_prior_only=true`, `calibrated_claim=false` |
| 4 | Ensemble and method-specific distributions are both saved | `method_results/<id>.json` + `ensemble_report.json`; `test_ac4_both_distributions_persisted` |
| 5 | Intrinsic-value weights and market-outcome weights are separate artifacts | `intrinsic_value_weights.json` vs `market_outcome_weights.json`; `refuse_reuse_market_as_intrinsic`; `test_ac5_*` |
| 6 | Leave-one-method-out and between-method disagreement diagnostics work on synthetic examples | `LeaveOneOutReport` + `BetweenMethodDisagreement`; `test_ac6_l1o_and_disagreement_synthetic`; CLI `l1o_max_abs_delta_median` / `disagreement_range` |

Additional: property tests — weights sum to 1; ineligible methods never enter mixture (`test_ineligible_never_in_mixture_property`).

## Example artifact summary
```text
vms phase8 --out /tmp/vms_phase8_smoke --seed 42 --fixture mature --n-draws 400
→ status=PHASE8_ENSEMBLE_NOT_INVESTMENT_ADVICE
→ schema_version=vms-0.2.phase8  implemented_phase=PHASE_8
→ production_mixture=false  production_calibration_status=CALIBRATION_INSUFFICIENT
→ research_mode=PRIOR_ONLY  research_protocol=PRIOR_ONLY_EQUAL_WEIGHT
→ research_mixture=true  ensemble_status=ENSEMBLE_UNCALIBRATED  calibrated_claim=false
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ artifacts: ensemble_report.json, intrinsic_value_weights.json,
             market_outcome_weights.json, method_results/
```

## Known gaps (honest)
- No real walk-forward calibration sample yet (Phase 11) — production ensemble always refused; `ENSEMBLE_CALIBRATED` is not emitted by Phase 8 `build_ensemble`.
- Market-pricing **estimator** deferred (Phase 9); market-outcome weight artifact is a separate labeled stub only.
- Equal-weight is exploratory `PRIOR_ONLY` only — not a calibrated claim.
- Soft suitability still ≠ mixture weight (Phase 7 invariant retained).
- Synthetic hand centers drive offline disagreement / L1O demos; not investment estimates.
- No exit-price / returns rewrite under 0.2 adaptive path (Phases 9–10).
