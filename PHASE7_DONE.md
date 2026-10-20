# Phase 7 — Entry-price-conditioned returns: DONE

Not started: Phase 8 (sensitivity / uncertainty attribution).

## Decisions recorded
| ID | Decision |
|---|---|
| DIVIDEND-NO-REINVEST-v1 | R=(VPS_H + cum_DPS_H − P0)/P0; cum DPS = Σ dividends[y]/shares[y]; no reinvestment; no buyback/issuance cash double-count |
| HORIZON-EQUITY-REMAINING-PV-v1 | EquityValue_H from PV_H(remaining FCFF H+1..N) + PV_H(TV_N), then Phase 6 bridge at H |
| ANNUALIZED-GEO-ENDYEAR-v1 | (1+R)^(1/H) − 1; end-of-year H |
| ENTRY-PRICE-GRID-v1 | spot × relative_to_spot; no “optimal buy price” claim |
| PRICE-REGIME-INVARIANT-v1 | Lower P0 improves pathwise dollar excess (and % return when X>0); price does not alter fundamental odds |

## Changed / new files
- `src/vms/returns/{horizon_value,formula,stats,distributions}.py` — horizon equity, TSR, stats, bundle
- `src/vms/pipeline.py` — `Phase7Run` / `run_returns`
- `src/vms/engine.py` — `build_return_distributions` / `returns_from_load` / `run` → Phase 7
- `src/vms/cli/main.py` — `vms returns`; demo through Phase 7; artifacts
- assumptions + docs + CI
- Tests: `test_returns.py` (9+), `test_cli_returns.py`, `test_return_properties.py`

## Tests
- **439 passed** (~175 s box; clean clone + uv/py3.11.17 + lock: **439 passed** in 191 s; `vms returns` exit 0, n_valid_return_paths=40, artifacts return_distribution_summary.json + path_returns.parquet).
- Leakage **6/6 KILLED**; invariant **7/7 KILLED**.

## Acceptance evidence

1. **Return formulas pass hand-worked examples.**
   - `test_holding_period_and_ann_geo_hand`, `test_horizon_ev_hand_fixture` (Gordon TV at H=N; remaining PV at H<N).

2. **Corporate actions not double-counted.**
   - DIVIDEND-NO-REINVEST-v1: only VPS + cum DPS; buybacks/issuance in share path only (`test_no_dividend_double_count_in_formula`).

3. **Lower entry improves pathwise returns (future paths fixed).**
   - `pathwise_returns_improve_at_lower_price` + `test_return_properties` / e2e: X invariant; dollar excess monotone; % return monotone when X>0.

4. **Changed fundamental posterior triggers recomputation.**
   - `test_changed_posterior_changes_returns` (different seeds → different fingerprint).

5. **No rule that lower price alone improves fundamental odds.**
   - `test_price_does_not_change_fundamental_odds`: initial_state invariant across prices; posterior sums to 1 from fundamentals.

6. **Quantiles / loss probs internally consistent.**
   - `test_cvar_and_quantile_consistency`: p01≤p05≤median; CVaR; P(loss) in [0,1].

7. **CLI / facade.**
   - `vms returns` → `return_distribution_summary.json` + `path_returns.parquet`; `ValuationEngine.build_return_distributions`.
   - Mixture + regime-conditional cells with support counts / rare-state flags.

## Limitations
1. Percentage-return monotonicity in P0 requires X=VPS+cum_DPS>0; dollar excess always monotone (documented).
2. Intermediate-horizon equity uses same path WACC as terminal DCF (no term-structure).
3. DPS uses dividends/diluted_shares per year (approximation for buy-and-hold cash received).
4. No Phase 8 sensitivity / attribution yet.
5. Suite ~3 min.

## New questions
1. Prefer share-weighted DPS path that tracks a single share lot through buybacks more literally?
2. Term-structure / rolling WACC for intermediate horizons?
3. Persist full return parquet partitioned by horizon by default?
