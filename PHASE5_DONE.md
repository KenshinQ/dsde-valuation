# Phase 5 — Relative valuation methods and PIT peer set: DONE (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE4_DONE.md](PHASE4_DONE.md).

Status: **all Phase 5 acceptance criteria pass** for P/E, P/B, EV/EBIT, EV/EBITDA, EV/Sales,
PIT peer construction/filtering, and robust multiple distributions.
Label: `ENGINEERING_PASS` for Phase 5 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** investment advice and does **not** claim investment value.
Phases 6+ (RIM/NAV/SOTP / router hardening / ensemble / exit-price / walk-forward)
are **not** claimed done.

> Note: an older VMS-0.1 `PHASE5_DONE.md` (path statements under 0.1 numbering) is
> superseded by this VMS-0.2 Phase 5 report. The 0.1 path-statement work remains in
> the codebase and is covered by retained `test_phase5_followups.py` / path suites.

## Changed / added files (VMS-0.2 Phase 5)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase5, PHASE_5
src/vms/methods/multiples/                  NEW: definitions, denominators, peers,
                                            aggregate, apply, cycle, plugins, run
src/vms/methods/protocol.py                 subject_metrics + peer_observations on context
src/vms/methods/registry.py                 bind Phase 5 plugins when IMPLEMENTED+enabled
src/vms/schemas/config.py                   MultiplesConfig + peer filter sidecar
src/vms/reporting/phase5_bundle.py          NEW: offline synthetic multiples emitter
src/vms/cli/main.py                         `vms phase5`
src/vms/assumptions.py                      PEER-MULTIPLE-RELATIVE-v1, NO-DOUBLE-EV-BRIDGE-v1,
                                            CYCLE-NORMALIZE-FLAG-v1
config/method_registry.yaml                 pe/pb/ev_* → IMPLEMENTED+enabled
config/default.yaml                         multiples: block; configuration_version phase5
config/*.yaml                               catalogs → phase5
examples/synthetic_mature_operating/        (phase4 retained; phase5 via CLI)
tests/unit/test_phase5_acceptance.py        NEW (§20 AC + hand fixtures)
tests/leakage/test_multiples_peer_leakage.py NEW
tests/integration/test_cli_phase5.py        NEW
PHASE5_DONE.md / README.md / docs/assumptions.md
```

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **577 passed** (Phase 4 was **565**; +12) |
| CLI | `vms phase5 --out /tmp/vms_phase5_smoke --seed 42 --paths 10 --years 2 --multiples-only` | `PHASE5_RELATIVE_MULTIPLES_NOT_INVESTMENT_ADVICE`; eligible_run includes pe/pb/ev_* |

## Acceptance criterion → evidence (§20 Phase 5 / §24)

| # | Criterion (SPEC §20 Phase 5) | Evidence |
|---|---|---|
| 1 | Each metric definition, denominator and bridge is explicit | `METRIC_DEFINITIONS` in `methods/multiples/definitions.py`; `test_ac1_each_metric_definition_denominator_and_bridge_explicit`; result `values.metric_definition` / `formula` / `claim_object` |
| 2 | Negative/near-zero denominator tests produce correct exclusions/warnings | `check_denominator`; `test_ac2_negative_near_zero_denominator_exclusions` → `INELIGIBLE_DENOMINATOR`, empty `values` |
| 3 | Peer membership and metrics use only PIT-available data | `build_peer_set` + `peer_known_at`; `test_ac3_ac4_pit_peer_membership_and_persisted_exclusions`; `test_ac3_future_peer_cannot_enter_historical_sample_via_method`; `tests/leakage/test_multiples_peer_leakage.py` |
| 4 | Peer set and exclusions are persisted with reasons | `PeerSetReport.included/excluded`; CLI `peer_diagnostics.json`; AC3/AC4 + CLI smoke |
| 5 | Outliers and small peer samples trigger documented robustness/uncertainty diagnostics | `aggregate_multiples` (median/winsorized/trimmed — never blind mean); flags `PEER_SCARCITY`, `SMALL_PEER_SAMPLE`, `HIGH_PEER_DISPERSION`; `test_ac5_outliers_and_small_sample_diagnostics` |
| 6 | EV- and equity-based methods do not get cross-bridged or double-counted | P/E & P/B: `ev_bridge_applied=false`; EV/*: bridge once via `bridge_ev_to_equity`; cross-apply → `BRIDGE_CONTRACT_MISMATCH`; `test_ac6_equity_methods_no_ev_bridge_ev_methods_bridge_once`; assumption `NO-DOUBLE-EV-BRIDGE-v1` |

Additional: EV/Sales labeled `RELATIVE_PRICING_ONLY`; cyclical trailing without mid-cycle → `CYCLE_ESTIMATE_LOW_CONFIDENCE` (`test_cyclical_trailing_without_midcycle_flagged`); hand fixtures for P/E and EV/EBIT (`test_hand_fixture_pe_equity_and_ev_ebit_bridge`); Phase 4 cash-flow methods remain enabled and green.

## Example artifact summary
```text
vms phase5 --out /tmp/vms_phase5_smoke --seed 42 --paths 10 --years 2 --multiples-only
→ status=PHASE5_RELATIVE_MULTIPLES_NOT_INVESTMENT_ADVICE
→ schema_version=vms-0.2.phase5  implemented_phase=PHASE_5
→ eligible_run=[pe, pb, ev_ebit, ev_ebitda, ev_sales]
→ ensemble=null
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ artifacts: method_results.json, peer_diagnostics.json, route_report.json
```

## Known gaps (honest)
- No RIM / NAV / SOTP (Phase 6).
- Router soft-suitability / disagreement hardening beyond current gates (Phase 7).
- No calibrated ensemble — production mixture forbidden (Phase 8).
- Market-pricing **estimator** deferred (schemas only; Phase 9).
- Mid-cycle normalization is flag/hook level (`CYCLE_ESTIMATE_LOW_CONFIDENCE`); full cycle model not built.
- Peer comparability filters (size/growth/profitability/leverage) are configured and tested via attrs injection; production industry peer graphs remain data-dependent.
- No exit-price / returns rewrite under 0.2 adaptive path (Phases 9–10).
- No walk-forward release gates (Phase 11).
