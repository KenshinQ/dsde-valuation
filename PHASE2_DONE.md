# Phase 2 — completion report (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE1_DONE.md](PHASE1_DONE.md), [PHASE0_DONE.md](PHASE0_DONE.md).

Status: **all Phase 2 acceptance criteria pass** for the economic-profile classifier and
declarative method registry.
Label: `ENGINEERING_PASS` for Phase 2 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** a valuation and does **not** claim investment value.
Phases 3+ (drivers/paths/method math/ensemble/market-pricing) are **not** claimed done.

## Changed / added files (VMS-0.2 Phase 2)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase2, PHASE_2
src/vms/schemas/contracts.py                OutputBasis; MethodRegistryEntry Phase-2 declarations
src/vms/schemas/__init__.py                 export OutputBasis
src/vms/profiles/                           NEW: features, rules, classifier, report, overrides, fixtures
src/vms/methods/                            NEW: protocol, eligibility hard gates, registry, DeclaredStubMethod
src/vms/router/                             NEW: route_methods skeleton (candidates + gates only)
src/vms/cli/main.py                         `vms profile`, `vms route`
config/method_registry.yaml                 11 declared methods, all NOT_IMPLEMENTED / enabled=false
config/router.yaml / profiles.yaml          version → phase2
config/default.yaml                         configuration_version → phase2
config/profile_overrides.yaml               NEW empty versioned override catalog
config/classifier/industry_aux_keywords.yaml  NEW (aux keywords out of Python sources)
examples/profile_fixtures/                  NEW 5 synthetic fixtures + README
tests/unit/test_profiles_phase2.py          NEW
tests/unit/test_methods_registry_phase2.py  NEW
tests/integration/test_cli_profile_route.py NEW
tests/unit/test_package_skeleton.py         Phase 2 packages required; ensemble/market_pricing still absent
tests/unit/test_contracts_v02.py / test_config.py / schema_version hardcodes
PHASE2_DONE.md / README.md / pyproject.toml
```

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **542 passed** (Phase 1 was **522**; +20) |
| CLI | `vms profile --fixture examples/profile_fixtures/mature_operating.json` | `MATURE_OPERATING`, investment label unsetablished |
| CLI | `vms route --fixture …/bank.json --attempt-stubs` | `INSUFFICIENT_METHOD_COVERAGE`, eligible_count=0, no values |

## Acceptance criterion → evidence

| # | Criterion (SPEC §20 Phase 2) | Evidence |
|---|---|---|
| 1 | Synthetic mature industrial, bank, high-growth negative-FCF, cyclical and holding fixtures route to expected profile(s) or visibly return low confidence | Fixtures in `examples/profile_fixtures/`; `tests/unit/test_profiles_phase2.py::test_synthetic_fixtures_route_to_expected_profile` (5 cases). Smoke: mature→MATURE_OPERATING, growth→GROWTH_OR_REINVESTMENT_HEAVY, bank→FINANCIAL_INSTITUTION, cyclical→CYCLICAL_OPERATING, holding→HOLDING_OR_CONGLOMERATE. Industry-only → low confidence (`test_industry_alone_insufficient_for_hard_class`). |
| 2 | Classifier output can be traced to feature values and rule IDs | `ProfileReport.rule_hits` / `flag_hits` with `rule_id`, `feature_refs`, `detail`; `feature_values` dump. Test: `test_classifier_output_traceable_to_features_and_rule_ids`. |
| 3 | Manual overrides are versioned and recorded | `config/profile_overrides.yaml` (`override_version`); `ManualOverrideStatus` on report. Test: `test_manual_override_versioned_and_recorded`. |
| 4 | No method runs before hard eligibility gates | `evaluate_hard_gates` / `route_methods(..., attempt_value_paths=True)`; stubs return `INELIGIBLE` with `METHOD_NOT_IMPLEMENTED` and empty `values`. Coverage `INSUFFICIENT_METHOD_COVERAGE` when none eligible — never a default DCF. Tests: `test_no_method_runs_before_hard_eligibility_gates`, `test_holding_coverage_gap_not_default_dcf`, CLI `test_cli_route_insufficient_coverage`. |
| 5 | Every registered method declares targets, units, required fields and failure codes | `MethodRegistryEntry` requires `version`, `supported_targets`, `output_basis`, `failure_codes`; `required_fields` declared. Populated registry (11 methods). Test: `test_every_registered_method_declares_targets_units_fields_failure_codes`. Enabling NOT_IMPLEMENTED still rejected. |

## Example artifact summary
```text
vms profile --fixture examples/profile_fixtures/mature_operating.json
→ primary_profile=MATURE_OPERATING  confidence=0.87
→ rule_hit_ids=[R_MATURE_POS_FCF_STABLE, R_MATURE_MODERATE]
→ schema_version=vms-0.2.phase2  implemented_phase=PHASE_2
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED

vms route --fixture examples/profile_fixtures/bank.json --attempt-stubs
→ profile_primary=FINANCIAL_INSTITUTION
→ coverage_status=INSUFFICIENT_METHOD_COVERAGE  eligible_count=0
→ fcff_dcf INELIGIBLE (not implemented + profile exclusion)
```

## Known gaps (honest)
- No driver paths, financial-statement projection rewrite, or Monte Carlo for VMS-0.2 (Phase 3).
- No FCFF/FCFE/DDM/RIM/multiples/NAV/SOTP **math** — methods are declared stubs only (Phases 4–6).
- Soft suitability is conceptual-fit diagnostic only; not ensemble weights (Phase 7–8).
- No market-pricing / exit-price / returns rewrite under 0.2 router (Phases 9–10).
- No walk-forward calibration (Phase 11).
- Classifier is rule-based baseline only; optional probabilistic classifier deferred (§7.3).
- Profile features for real PIT snapshots are not yet auto-extracted from `PITSnapshot` (fixtures supply `ProfileFeatureBundle` directly); wiring from snapshot metrics is a follow-up, not required to claim Phase 2.
- Legacy VMS-0.1 `vms project|value|returns|…` pipeline remains importable and tested; it is **not** the VMS-0.2 adaptive router path.
- Engineering pass ≠ investment alpha.

## Failed criteria
None. No criterion was weakened.
