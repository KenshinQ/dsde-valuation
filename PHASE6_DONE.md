# Phase 6 — RIM, NAV and SOTP methods: DONE (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE5_DONE.md](PHASE5_DONE.md).

Status: **all Phase 6 acceptance criteria pass** for residual income (RIM), asset-based NAV,
and SOTP with segment/asset contracts and reconciliation.
Label: `ENGINEERING_PASS` for Phase 6 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** investment advice and does **not** claim investment value.
Phases 7+ (router hardening / ensemble / exit-price / walk-forward) are **not** claimed done.

> Note: an older VMS-0.1 `PHASE6_DONE.md` (DCF & multiple cross-check under 0.1 numbering) is
> superseded by this VMS-0.2 Phase 6 report. The 0.1 DCF/bridge work remains in the codebase
> under `vms.valuation` / `vms.equity_bridge` and is covered by retained valuation suites.

## Changed / added files (VMS-0.2 Phase 6)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase6, PHASE_6
src/vms/methods/rim/                        NEW: clean-surplus assess + RIM PV math + plugin
src/vms/methods/nav/                        NEW: explicit FV asset/claim NAV + plugin
src/vms/methods/sotp/                       NEW: segment reconcile + holding discount + plugin
src/vms/methods/asset_based/                NEW: run_eligible_phase6_methods orchestrator
src/vms/methods/protocol.py                 rim_inputs / nav_inputs / sotp_inputs on context
src/vms/methods/registry.py                 bind Phase 6 plugins when IMPLEMENTED+enabled
src/vms/assumptions.py                      RIM-*/NAV-*/SOTP-* assumption IDs
src/vms/reporting/phase6_bundle.py          NEW: offline synthetic RIM/NAV/SOTP emitter
src/vms/cli/main.py                         `vms phase6`
config/method_registry.yaml                 residual_income/nav/sotp → IMPLEMENTED+enabled
config/*.yaml                               catalogs → phase6
examples/profile_fixtures/financial_institution.json  (renamed from bank.json)
tests/unit/test_phase6_acceptance.py        NEW (§20 AC + hand fixtures)
tests/integration/test_cli_phase6.py        NEW
PHASE6_DONE.md / README.md / docs/assumptions.md
```

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **587 passed** (Phase 5 was **577**; +10) |
| CLI | `vms phase6 --out /tmp/vms_phase6_smoke --seed 42 --fixture financial` | `PHASE6_RIM_NAV_SOTP_NOT_INVESTMENT_ADVICE`; eligible_run includes `residual_income`; industrial FCFF/EV EBITDA disabled |
| CLI | `vms phase6 --fixture holding_gap` | eligible_run=[]; NAV/SOTP `unsupported` + data_gap |

## Acceptance criterion → evidence (§20 Phase 6 / §24)

| # | Criterion (SPEC §20 Phase 6) | Evidence |
|---|---|---|
| 1 | RIM validates book-equity and clean-surplus conditions or becomes ineligible | `assess_clean_surplus` / `residual_income_value`; `test_ac1_rim_clean_surplus_or_ineligible` (UNASSESSABLE / CLEAN_SURPLUS_FAIL / NEGATIVE_BOOK_EQUITY); hand fixture `test_ac1_rim_hand_fixture_numeric` (equity=120) |
| 2 | NAV requires explicit asset/claim assumptions; book ≠ fair without justification | `book_totals_are_not_nav`; `compute_nav` rejects fair=book with empty justification; `test_ac2_nav_requires_explicit_fair_not_raw_book`; assumption `NAV-BOOK-NE-FAIR-v1` |
| 3 | SOTP reconciles segments, group costs, debt, minorities and inter-segment items | `compute_sotp` reconciliation identity; `test_ac3_sotp_reconciles_segments_and_group_items`; inter-segment mismatch → `INTER_SEGMENT_UNRECONCILED`; holding discount explicit (`SOTP-HOLDING-DISCOUNT-EXPLICIT-v1`) |
| 4 | Synthetic bank and holding fixtures route to appropriate methods or visible unsupported | `test_ac4_financial_routes_to_rim_industrial_fcff_disabled` (FINANCIAL_INSTITUTION → RIM; FCFF/EV EBITDA ineligible; P/B eligible on relative target); `test_ac4_holding_routes_to_sotp_nav_or_visible_gap`; CLI financial + holding / holding_gap |
| 5 | Missing segment/asset data cannot generate an apparently complete NAV result | `test_ac5_missing_asset_or_segment_cannot_look_complete`; CLI `holding_gap` → empty values + `unsupported` + data_gap; flags `APPARENTLY_COMPLETE_NAV_FORBIDDEN` |

Additional: no ensemble (`ensemble=null`); equity-side RIM has `ev_bridge_applied=false`; Phase 4/5 methods remain enabled and green.

## Example artifact summary
```text
vms phase6 --out /tmp/vms_phase6_smoke --seed 42 --fixture financial
→ status=PHASE6_RIM_NAV_SOTP_NOT_INVESTMENT_ADVICE
→ schema_version=vms-0.2.phase6  implemented_phase=PHASE_6
→ profile_primary=FINANCIAL_INSTITUTION
→ eligible_run=[residual_income]
→ industrial_fcff_disabled.fcff_dcf_eligible=false
→ ensemble=null
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ artifacts: method_results.json, route_report.json, profile_report.json
```

## Known gaps (honest)
- Router soft-suitability / disagreement hardening beyond current gates (Phase 7).
- No calibrated ensemble — production mixture forbidden (Phase 8).
- Market-pricing **estimator** deferred (schemas only; Phase 9).
- RIM path-bundle extraction is best-effort from statement projections; bank demo uses explicit rim_inputs schedules.
- SOTP segment values are configured/injected in Phase 6 (segment-level method recursion not built).
- No exit-price / returns rewrite under 0.2 adaptive path (Phases 9–10).
- No walk-forward release gates (Phase 11).
