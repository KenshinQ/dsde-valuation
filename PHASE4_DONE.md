# Phase 4 — completion report (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE3_DONE.md](PHASE3_DONE.md).

Status: **all Phase 4 acceptance criteria pass** for FCFF DCF, FCFE DCF, DDM,
eligibility gates, assumption contracts and diagnostics.
Label: `ENGINEERING_PASS` for Phase 4 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** investment advice and does **not** claim investment value.
Phases 5+ (multiples / RIM/NAV/SOTP / router hardening / ensemble / exit-price /
walk-forward) are **not** claimed done.

> Note: an older VMS-0.1 `PHASE4_DONE.md` (path sampler under 0.1 numbering) is
> superseded by this VMS-0.2 Phase 4 report.

## Changed / added files (VMS-0.2 Phase 4)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase4, PHASE_4
src/vms/methods/cash_flow/                  NEW: FCFF/FCFE/DDM math + plugins + run
src/vms/methods/protocol.py                 ValuationContext.loaded; MethodResult.diagnostics
src/vms/methods/registry.py                 bind IMPLEMENTED plugins (not stubs)
src/vms/methods/eligibility.py              (unchanged gates; plugins extend)
src/vms/router/route.py                     optional context_loaded / financial_paths
src/vms/reporting/phase4_bundle.py          NEW: offline synthetic method-results emitter
src/vms/cli/main.py                         `vms phase4`
src/vms/assumptions.py                      FCFE-DCF-v1, COST-OF-EQUITY-DISCOUNT-v1, DDM-v1
config/method_registry.yaml                 fcff_dcf/fcfe_dcf/ddm → IMPLEMENTED+enabled
config/*.yaml                               configuration_version / catalogs → phase4
examples/synthetic_mature_operating/        run_phase4.py + README Phase 4 section
tests/unit/test_phase4_acceptance.py        NEW (§20 AC + property tests)
tests/integration/test_cli_phase4.py        NEW
tests/unit/test_methods_registry_phase2.py  updated for implemented methods
tests/integration/test_cli_profile_route.py bank/holding coverage expectations
PHASE4_DONE.md / README.md / docs/assumptions.md
```

Retained / wrapped from VMS-0.1: `vms.valuation.dcf.dcf_fcff`, `vms.valuation.wacc`,
`vms.equity_bridge` — used only inside the FCFF plugin under the registry/router
(no silent default-DCF bypass).

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **565 passed** (Phase 3 was **553**; +12) |
| CLI | `vms phase4 --out /tmp/vms_phase4_smoke --seed 42 --paths 20 --years 3` | `PHASE4_CASHFLOW_METHODS_NOT_INVESTMENT_ADVICE`; eligible_run=`fcff_dcf,fcfe_dcf,ddm` |

## Acceptance criterion → evidence

| # | Criterion (SPEC §20 Phase 4) | Evidence |
|---|---|---|
| 1 | Hand-calculated fixtures match within tolerance | `test_phase4_acceptance.py::test_ac1_fcff_hand_fixture`, `test_ac1_fcfe_hand_fixture`, `test_ac1_ddm_hand_fixture`; also legacy `test_valuation.py::test_dcf_hand_fixture_matches_present_value` |
| 2 | FCFF uses WACC; FCFE/DDM use cost of equity | `test_ac2_fcff_uses_wacc_fcfe_ddm_use_ke`; `CashFlowTypeError` on FCFE×WACC; `WACC_SUBSTITUTION_FORBIDDEN` when `discount_rate_kind!="COST_OF_EQUITY"` |
| 3 | Invalid discount-rate / terminal-growth rejected with reason codes | `test_ac3_invalid_discount_terminal_growth_rejected`; `test_property_invalid_wacc_le_g_never_valid` (Hypothesis); codes `WACC_G_MARGIN_FAIL` / `KE_G_MARGIN_FAIL` + `NO_SILENT_DENOMINATOR_REPAIR` |
| 4 | Dividend and debt/share paths not double-counted | `test_ac4_no_double_count_dividends_debt_share` — FCFE/DDM set `ev_bridge_applied=false`; FCFF alone uses EV→equity bridge |
| 5 | DCF TV share and key sensitivities reported | `test_ac5_tv_fraction_and_sensitivities_reported`; method `values.tv_fraction` + `values.sensitivities` (`rate_plus/minus`, `g_plus/minus`) |
| 6 | Ineligible DDM returns structured reason, not fabricated value | `test_ac6_ineligible_ddm_structured_reason_not_fabricated`; `payout_modelable` → `ABSENT_DIVIDENDS` / `ERRATIC_PAYOUT` / `PAYOUT_NOT_MODELABLE`; empty `values` |

Additional: `test_property_ineligible_method_contributes_no_values`; router still returns
`INSUFFICIENT_METHOD_COVERAGE` for holding×ASSET_NAV (no default DCF).

## Example artifact summary
```text
vms phase4 --out /tmp/vms_phase4_smoke --seed 42 --paths 20 --years 3
→ status=PHASE4_CASHFLOW_METHODS_NOT_INVESTMENT_ADVICE
→ schema_version=vms-0.2.phase4  implemented_phase=PHASE_4
→ coverage_status=METHODS_ELIGIBLE
→ eligible_run=[fcff_dcf, fcfe_dcf, ddm]
→ ensemble=null
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ artifacts: method_results.json, route_report.json, profile_report.json
```

## Known gaps (honest)
- No relative multiples / PIT peer valuation (Phase 5).
- No RIM / NAV / SOTP (Phase 6).
- Router soft-suitability / disagreement hardening beyond Phase 2+4 gates (Phase 7).
- No calibrated ensemble — production mixture forbidden (Phase 8).
- Market-pricing **estimator** deferred (schemas only; Phase 9).
- No exit-price / returns rewrite under 0.2 adaptive path (Phases 9–10).
- No walk-forward release gates (Phase 11).
- Discount rates use config ASSUMPTIONS (RF/ERP/beta), not a live PIT CGB adapter.
- Legacy `vms value` remains the 0.1 FCFF pipeline; prefer `vms phase4` for the adaptive path.
- Engineering pass ≠ investment alpha.

## Failed criteria
None. No criterion was weakened.
