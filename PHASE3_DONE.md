# Phase 3 — completion report (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE2_DONE.md](PHASE2_DONE.md).

Status: **all Phase 3 acceptance criteria pass** for operating-company drivers, fundamental
regimes, correlated path sampling, statement projection and capital-allocation policies.
Label: `ENGINEERING_PASS` for Phase 3 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** a valuation and does **not** claim investment value.
Phases 4+ (method math / multiples / ensemble / exit-price estimator / walk-forward release)
are **not** claimed done.

> Note: an older VMS-0.1 `PHASE3_DONE.md` (regimes-only under 0.1 numbering) is superseded by
> this VMS-0.2 Phase 3 report.

## Changed / added files (VMS-0.2 Phase 3)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase3, PHASE_3
src/vms/market_pricing/                     NEW: §14.3 schemas (COMPRESSED/NORMAL/EXPANDED/DISLOCATION)
src/vms/regimes/market.py                   cross-link; UNAVAILABLE carrier never from fundamentals
src/vms/regimes/rule_based.py               optional DISTRESS mass reserved (DISTRESS_RULE_NOT_ACTIVE)
src/vms/schemas/config.py                   FUNDAMENTAL_STATES + optional DISTRESS
src/vms/reporting/phase3_bundle.py          NEW: offline synthetic path-bundle emitter
src/vms/cli/main.py                         `vms phase3`
config/*.yaml                               configuration_version / catalogs → phase3
examples/synthetic_mature_operating/        run_phase3.py + README Phase 3 section
tests/unit/test_market_pricing_schemas.py   NEW
tests/unit/test_phase3_acceptance.py        NEW (§20 AC mapping)
tests/integration/test_cli_phase3.py        NEW
tests/unit/test_package_skeleton.py         Phase 3 modules; ensemble still absent
(hardcoded schema_version asserts bumped to vms-0.2.phase3)
PHASE3_DONE.md / README.md / pyproject.toml
```

Retained / migrated from VMS-0.1 (adapted, not rewritten from scratch):
`drivers/`, `regimes/` (fundamental), `sampling/`, `statements/`, `capital_allocation/` —
already covering §8–§9 mechanics; Phase 3 wires them under 0.2 schema + profile gates.

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **553 passed** (Phase 2 was **542**; +11) |
| CLI | `vms phase3 --out /tmp/vms_phase3_smoke --seed 42 --paths 20 --years 3` | `PHASE3_PATH_BUNDLE_NOT_A_VALUATION`, financial_n_valid=20, market_pricing=UNAVAILABLE |

## Acceptance criterion → evidence

| # | Criterion (SPEC §20 Phase 3) | Evidence |
|---|---|---|
| 1 | Valid synthetic financial paths reconcile accounting invariants | `tests/unit/test_phase3_acceptance.py::test_ac1_valid_paths_reconcile_invariants`; also `test_path_statements.py::test_all_valid_paths_pass_invariants`, `test_policies_invariants.py` |
| 2 | Negative income, tax-loss, negative FCF, capex, WC swings, debt and dilution have explicit tests | `test_ac2_negative_income_tax_loss_fcf_capex_wc_debt_dilution`; also `test_projection.py::test_negative_earnings_and_tax_losses`, `test_path_statements.py::test_forced_negative_ebit_tax_loss_flags`, `test_wc_capex_dilution_path_mechanics`, `test_policies_invariants.py::test_fixed_payout_and_negative_income` |
| 3 | Fundamental and market-pricing state schemas are distinct | `test_ac3_fundamental_and_market_pricing_schemas_distinct`; `test_market_pricing_schemas.py` (disjoint vocabularies; cross-validation fails); `test_regimes.py::test_fundamental_and_market_schemas_distinct` |
| 4 | Fixed seed reproduces the path bundle | `test_ac4_fixed_seed_reproduces_path_bundle`; `test_sampling.py::test_fixed_seed_reproduces_paths`; CLI `test_cli_phase3_artifacts` (identical run_id) |
| 5 | Sparse history results trigger low-confidence/shrinkage flags | `test_ac5_sparse_history_triggers_low_confidence_shrinkage`; `test_distributions.py::test_sparse_history_shrinks_and_flags` |

Additional: financial institutions are not forced onto industrial FCFF drivers —
`test_financial_institution_not_forced_onto_industrial_fcff_drivers` (`UNSUPPORTED_PROFILE`).

## Example artifact summary
```text
vms phase3 --out /tmp/vms_phase3_smoke --seed 42 --paths 20 --years 3
→ status=PHASE3_PATH_BUNDLE_NOT_A_VALUATION
→ schema_version=vms-0.2.phase3  implemented_phase=PHASE_3
→ sampler_version=PATH-SAMPLER-1  financial_n_valid=20
→ market_pricing_status=UNAVAILABLE (estimator Phase 9)
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ artifacts: simulation_bundle.json, financial_path_bundle.json, state_posterior.json
```

## Known gaps (honest)
- No FCFF/FCFE/DDM **method engines** under the Phase-2 registry (Phase 4).
- No multiples / PIT peer valuation (Phase 5).
- No RIM/NAV/SOTP (Phase 6).
- Router soft-suitability / comparison hardening beyond Phase 2 gates (Phase 7).
- No calibrated ensemble (Phase 8).
- Market-pricing **estimator** deferred — schemas only (`COMPRESSED`/`NORMAL`/`EXPANDED`/`DISLOCATION`); posterior UNAVAILABLE (Phase 9).
- No exit-price / returns rewrite under 0.2 adaptive path (Phases 9–10).
- No walk-forward release gates (Phase 11).
- Profile-specific bank/insurance driver families remain `UNSUPPORTED_PROFILE` (explicit flag).
- Optional `DISTRESS` fundamental state is config-allowed; rule-based mass currently reserved at 0 (`DISTRESS_RULE_NOT_ACTIVE`).
- Legacy `vms value|returns|…` pipeline remains importable; it is **not** the VMS-0.2 adaptive method path.
- Engineering pass ≠ investment alpha.

## Failed criteria
None. No criterion was weakened.
