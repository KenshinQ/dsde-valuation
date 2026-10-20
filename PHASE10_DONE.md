# Phase 10 — DSDE adapter & release readiness: DONE

Stopped after Phase 10 (no Phase 11 invented).

## Decisions recorded
| ID | Decision |
|---|---|
| OUTPUT-CONTRACT-v1 | All public results/artifacts stamp `schema_version: vms-0.1.0` |
| DSDE-ADAPTER-OPTIONAL-v1 | `vms.adapters.dsde` documents consumer view; DSDE package never required; discovery via importlib only |
| NO-LEGACY-IMPORT-v1 | Never import legacy PIT/FTD/DV1 / static `dsde*` (AST-enforced) |
| INVESTMENT-DEFAULT-v1 | `ValuationRunResult.labels.investment_value` defaults to `INVESTMENT_VALUE_NOT_ESTABLISHED` |
| CALIBRATION-SYNTHETIC-ONLY-v1 | Model card + labels: calibration INCONCLUSIVE / SYNTHETIC_ONLY for VMS-0.1 |
| ENGINE-RUN-FACADE-v1 | `ValuationEngine.run(request, data_bundle, config) -> ValuationRunResult` |

## Changed / new files
- `src/vms/adapters/{__init__,dsde}.py` — optional DSDE consumer adapter
- `src/vms/result.py` — `ValuationRunResult`
- `src/vms/engine.py` — full `run` orchestration
- `src/vms/__init__.py` — `SCHEMA_VERSION=vms-0.1.0`, `IMPLEMENTED_PHASE=PHASE_10`, `__version__=0.1.0`
- `docs/model_card.md` — filled (purpose, profiles, assumptions, limitations, investment policy)
- `docs/data_contracts.md` — OUTPUT-CONTRACT-v1 section
- `docs/architecture.md` — Phase 10 end-to-end
- `README.md` — e2e demo commands + status
- `scripts/e2e_offline_demo.sh` — offline CLI path Phases 0–9 + asserts
- `PHASE10_DONE.md`, `RELEASE_NOTES.md`
- Tests: `test_dsde_adapter.py`, `test_engine_run.py`, package skeleton Phase 10
- CI: e2e script step; schema assertions → `vms-0.1.0`

## Acceptance evidence (§18 Phase 10)

1. **Valuation engine runs without DSDE installed.**
   - `dsde_availability()["dsde_present"] is False` in tests; full pytest green; `import vms` alone.

2. **DSDE integration only through documented interfaces.**
   - `vms.adapters.dsde`: `DSDEConsumerView`, `consumer_view_from_result`, `try_notify_dsde`, `dsde_availability`.
   - No static `import dsde*` (AST test); dynamic importlib only inside `try_notify_dsde`.

3. **Consumers retrieve value/return distributions + uncertainty diagnostics without internals.**
   - `DSDEConsumerView` exposes `return_mixture`, `valuation_summary`, `uncertainty_diagnostics`, labels.

4. **Clean checkout runs end-to-end on synthetic data.**
   - `scripts/e2e_offline_demo.sh` + CI step; validate→…→evaluate; asserts ENGINEERING keys + `INVESTMENT_VALUE_NOT_ESTABLISHED`.

5. **Unsupported profiles and limitations documented.**
   - `docs/model_card.md` §§2–3,7; `docs/architecture.md`; RELEASE_NOTES.

## Definition of Done (§21) checklist

| # | Criterion | Evidence |
|---|---|---|
| 1 | All phase acceptance criteria pass | PHASE0–PHASE10_DONE.md |
| 2 | Clean checkout offline synthetic demo | `scripts/e2e_offline_demo.sh`; CI |
| 3 | PIT and accounting gates enforced | Phase 1–2 gates + mutation checks |
| 4 | Path-wise financials, valuation & entry-price returns produced | Phases 5–7; engine.run |
| 5 | DCF/multiple assumptions explicit & auditable | assumptions register + valuation artifacts |
| 6 | Sensitivity, calibration, walk-forward reports | Phases 8–9; e2e |
| 7 | DSDE adapter optional | `vms.adapters.dsde`; tests with DSDE absent |
| 8 | Supported/unsupported profiles documented | model_card + architecture |
| 9 | No profitability claim without predeclared leakage-safe OOS evidence | labels always NOT_ESTABLISHED on synthetic; **no alpha claim** |

## Tests
- Full pytest (box + clean py3.11 clone) — see Chinese report / RELEASE_NOTES for counts.
- Leakage + invariant mutation checks remain green.

## Remaining known limitations (real A-share)
1. **HiThink / live provider adapter is future work** — VMS-0.1 ingests offline CSV/Parquet + SYNTHETIC only.
2. Calibration on real A-share OOS not established.
3. Banks/insurance/brokerages unsupported for FCFF projection.
4. No FX conversion; non-CNY blocked.
5. HMM market regimes deferred.
6. Gaussian copula understates tail dependence.
