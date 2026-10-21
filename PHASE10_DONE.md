# Phase 10 — Return distributions and DSDE-facing contract: DONE (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior: [PHASE9_DONE.md](PHASE9_DONE.md).

Status: **all Phase 10 acceptance criteria pass** for Track B exit-price-conditioned total returns,
entry-price grid, multi-horizon summaries, pathwise price invariant, posterior recompute,
quantile/ES consistency, and optional DSDE public contract. Label: `ENGINEERING_PASS` for
Phase 10 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** investment advice and does **not** claim investment value.
**No** `INVESTMENT_VALUE_SUPPORTED`. **No** `ENSEMBLE_CALIBRATED` from returns alone.
Phases 11+ (walk-forward / docs release) are **not** claimed done.

> Note: an older VMS-0.1 `PHASE10_DONE.md` (DSDE adapter & release readiness under 0.1 numbering)
> is superseded by this VMS-0.2 Phase 10 report. The 0.1 adapter surface remains reachable via
> `vms.adapters.dsde` and is now a package under `src/vms/adapters/dsde/` with versioned
> `ReturnDistributionExport` / `DSDEConsumerView` contracts.

## Changed / added files (VMS-0.2 Phase 10)
```
src/vms/__init__.py                         SCHEMA_VERSION=vms-0.2.phase10, PHASE_10
src/vms/assumptions.py                      TRACK-B / SHAREHOLDER-DIST / NO-DOUBLE-COUNT-CA /
                                            RETURN-RECOMPUTE / PHASE10-DSDE-PUBLIC-CONTRACT
src/vms/returns/formula.py                  return_components; Phase 10 cite helper
src/vms/returns/stats.py                    components + ES/quantile consistency flags
src/vms/returns/track_b.py                  NEW: Track B return bundle from ExitPriceBundle
src/vms/returns/recompute.py                NEW: posterior-change recompute hook
src/vms/returns/__init__.py                 exports Track B + recompute
src/vms/adapters/dsde/                      NEW package (was single dsde.py)
  contract.py / export.py / notify.py / __init__.py
src/vms/adapters/__init__.py                re-exports package
src/vms/engine.py                           build_return_distributions_from_exit facade
src/vms/reporting/phase10_bundle.py         NEW offline emitter → return_distribution_summary.json
src/vms/cli/main.py                         `vms phase10`
config/*.yaml                               versions → phase10
tests/unit/test_phase10_acceptance.py       NEW (§20 AC1–AC5)
tests/property/test_return_track_b_properties.py NEW (§21.2)
tests/integration/test_cli_phase10.py       NEW
docs/assumptions.md                         regenerated
PHASE10_DONE.md / README.md
```

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **641 passed** (Phase 9 was **630**; +11) |
| CLI | `vms phase10 --out /tmp/vms_phase10_smoke --seed 42 --paths 20 --years 3 --horizons 1,3 --spot 10 --entry-prices 9,11` | `PHASE10_RETURN_DISTRIBUTIONS_NOT_INVESTMENT_ADVICE`; pathwise invariant true; DSDE absent |

## Acceptance criterion → evidence (§20 Phase 10 / §24)

| # | Criterion (SPEC §20 Phase 10) | Evidence |
|---|---|---|
| 1 | Hand-worked return fixtures pass, including dividends, share splits, buybacks/issuance where modeled | `test_ac1_hand_worked_dividend_fixture`; `test_ac1_hand_worked_split_and_buyback_no_double_count` (cash DPS only; buyback/issuance/split treatments labeled; `NO-DOUBLE-COUNT-CA-v1`); `test_ac1_track_b_uses_exit_not_intrinsic` |
| 2 | With fixed future-price paths, higher entry price cannot improve pathwise return | `test_ac2_higher_entry_cannot_improve_pathwise`; property `test_property_higher_entry_cannot_improve_pathwise_track_b`; CLI asserts `pathwise_higher_p0_cannot_improve` |
| 3 | Conditional updates to fundamental or market-state distributions trigger recomputation of affected outputs | `test_ac3_market_posterior_change_recomputs` via `recompute_returns_after_market_posterior_change`; CLI `recompute_demo.changed_vs_prior` |
| 4 | Quantiles, loss probabilities and expected shortfall are internally consistent | `test_ac4_quantile_loss_es_consistency`; `test_ac4_bundle_cells_consistent` (p01≤p05≤median; ES≤quantile; p_loss matches empirical) |
| 5 | VMS runs without DSDE; DSDE integration uses only public versioned contracts | `test_ac5_core_without_dsde_and_public_contract`; `dsde_availability()["required_for_core"] is False`; `ReturnDistributionExport` / `DSDEConsumerView` with `DSDE_CONTRACT_VERSION`; `try_notify_dsde` → `DSDE_ABSENT_NOOP` |

## Example artifact summary
```text
vms phase10 --out /tmp/vms_phase10_smoke --seed 42 --paths 20 --horizons 1,3 --spot 10
→ status=PHASE10_RETURN_DISTRIBUTIONS_NOT_INVESTMENT_ADVICE
→ schema_version=vms-0.2.phase10  implemented_phase=PHASE_10
→ compounding_convention=DIVIDEND-NO-REINVEST-v1
→ pathwise_higher_p0_cannot_improve=true
→ dsde_present=false  dsde_required_for_core=false
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ artifacts: return_distribution_summary.json, exit_price_summary.json, dsde_export.json
```

## Known gaps (honest)
- Walk-forward calibration / sensitivity attribution polish is **Phase 11**; returns alone do **not** establish investment value or calibrate ensembles.
- Documentation / model-card release polish is **Phase 12**.
- Mean-reversion market transitions remain configured placeholders (`UNSUPPORTED` estimation) from Phase 9.
- Legacy 0.1 Track-A horizon-equity `vms returns` path remains importable for back-compat but is **not** the VMS-0.2 Track B contract.
- No Kelly / portfolio sizing (out of scope; belongs to DSDE decision layer).
- Synthetic offline paths; no claim that return distributions are investment-relevant.
