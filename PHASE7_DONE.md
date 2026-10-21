# Phase 7 — Router hardening and method comparison: DONE (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE6_DONE.md](PHASE6_DONE.md).

Status: **all Phase 7 acceptance criteria pass** for deterministic routing logs, soft
suitability diagnostics, compatibility gates, normalization with retained method
identity, and disagreement reports without a calibrated ensemble.
Label: `ENGINEERING_PASS` for Phase 7 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** investment advice and does **not** claim investment value.
Phases 8+ (calibrated ensemble / exit-price estimator / walk-forward) are **not** claimed done.

> Note: an older VMS-0.1 `PHASE7_DONE.md` (entry-price-conditioned returns under 0.1 numbering)
> is superseded by this VMS-0.2 Phase 7 report. The 0.1 returns work remains in
> `vms.returns` / legacy `pipeline.Phase7Run` and is covered by retained returns suites.

## Changed / added files (VMS-0.2 Phase 7)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase7, PHASE_7
src/vms/schemas/contracts.py                ClaimStatus.ENSEMBLE_UNCALIBRATED
src/vms/methods/eligibility.py              soft_suitability docstring (≠ weights)
src/vms/router/suitability.py               NEW: 7 visible soft dimensions (§11.3)
src/vms/router/compatibility.py             NEW: target/horizon/basis checker (§13.2)
src/vms/router/compare.py                   NEW: normalize + disagreement; refuse blend
src/vms/router/route.py                     hardened MethodConsideration log (§11.4)
src/vms/router/__init__.py                  exports
src/vms/reporting/phase7_bundle.py          NEW: offline eligibility + comparison emitter
src/vms/cli/main.py                         `vms phase7`, `vms compare-methods`; route → method_eligibility.json
config/router.yaml / default.yaml / …       versions → phase7
tests/unit/test_phase7_acceptance.py        NEW (§20 AC1–AC5)
tests/integration/test_cli_phase7.py        NEW
PHASE7_DONE.md / README.md / test hardcodes
```

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **598 passed** (Phase 6 was **587**; +11) |
| CLI | `vms phase7 --out /tmp/vms_phase7_smoke --seed 42 --fixture mature` | `PHASE7_ROUTER_COMPARE_NOT_INVESTMENT_ADVICE`; ensemble_status=`ENSEMBLE_UNCALIBRATED`; combined_value=null |
| CLI | `vms phase7 --force-no-eligible` | `INSUFFICIENT_METHOD_COVERAGE`; eligible_count=0 |
| CLI | `vms compare-methods --out … --fixture mature` | writes `method_comparison.json` |
| CLI | `vms route --out …` | writes `method_eligibility.json` with per-method hard gates + soft dims |

## Acceptance criterion → evidence (§20 Phase 7 / §24)

| # | Criterion (SPEC §20 Phase 7) | Evidence |
|---|---|---|
| 1 | Router logs every considered method, hard-gate result, score dimensions, selected/runnable status and reason | `MethodConsideration` + `method_eligibility_payload`; `test_ac1_router_logs_considerations`; CLI `method_eligibility.json` |
| 2 | Same context/config produces the same route | `test_ac2_routing_deterministic` (full `model_dump` equality); candidates sorted by `method_id` |
| 3 | Incompatible target/horizon/output basis cannot be combined | `check_combination_compatibility`; `test_ac3_incompatible_cannot_combine` (EV↔EQUITY without bridge, horizon mismatch, intrinsic vs MARKET_EXIT_PRICE); phase7 `incompatible_demo_compatible=false` |
| 4 | Method results retain their identity after normalization | `NormalizedMethodValue.method_id` / `retained_identity`; `test_ac4_normalization_retains_identity`; disagreement range preserved; blend request → `ENSEMBLE_UNCALIBRATED`, `combined_value=null` |
| 5 | Profile with no eligible method → `INSUFFICIENT_METHOD_COVERAGE`, not default DCF | `test_ac5_no_eligible_returns_insufficient_coverage_not_default_dcf`; CLI `--force-no-eligible`; notes contain “not defaulting to DCF”; fcff_dcf not selected |

Additional: soft suitability always exposes all 7 §11.3 dimensions separately; `ensemble_weight=None`; `calibration_evidence=0.0` in Phase 7; suitability ≠ mixture weight (`test_soft_suitability_requires_all_dimensions_no_opaque_score`).

## Example artifact summary
```text
vms phase7 --out /tmp/vms_phase7_smoke --seed 42 --fixture mature
→ status=PHASE7_ROUTER_COMPARE_NOT_INVESTMENT_ADVICE
→ schema_version=vms-0.2.phase7  implemented_phase=PHASE_7
→ profile_primary=MATURE_OPERATING
→ coverage_status=METHODS_ELIGIBLE
→ disagreement.range=300.0 (fcff/fcfe/ddm hand medians)
→ ensemble_status=ENSEMBLE_UNCALIBRATED  combined_value=null
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ artifacts: method_eligibility.json, method_comparison.json, route_report.json
```

## Known gaps (honest)
- No calibrated / production ensemble mixture (Phase 8). Equal-weight and suitability-proportional blends remain forbidden as production defaults.
- Leave-one-method-out ensemble sensitivity deferred to Phase 8 (requires an ensemble).
- Market-pricing **estimator** deferred (schemas only; Phase 9).
- Soft suitability dimensions are deterministic heuristics / priors — not OOS calibration evidence.
- Comparison smoke uses hand medians for disagreement demo when routing a fixture without re-running full MC method math.
- No exit-price / returns rewrite under 0.2 adaptive path (Phases 9–10).
- No walk-forward release gates (Phase 11).
