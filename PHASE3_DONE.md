# Phase 3 — Fundamental regimes and driver distributions: DONE

Scope: SPEC §7.3–7.4, §8.1, §18 Phase 3, plus the Phase 2 follow-up decisions (committed separately in 301fa63).
Not started: Phase 4 (dependence, joint sampling, paths).

## Changed / new files
- `src/vms/regimes/` (new package, previously an empty Phase 3 stub):
  - `schemas.py`: `FundamentalRegimePosterior` (kind FUNDAMENTAL, inputs PIT_FUNDAMENTALS_ONLY), `MarketRegimePosterior` (kind MARKET; UNAVAILABLE ⇒ no probabilities + reason), `PeriodPosterior`, `FeatureRow`, `TransitionModel`, `validate_probabilities` (finite, ≥0, Σ=1 ± 1e-9).
  - `features.py`: TTM revenue growth yoy, TTM recurring EBIT margin and its yoy change, from snapshot financials only.
  - `rule_based.py`: `RuleBasedClassifier` (FUND-RULES): soft logistic memberships, forward filter only.
  - `transitions.py`: Dirichlet(stay, move) prior, annual-step soft counts, support counts and flags, `propagate`.
  - `hmm.py`: `RegimeModel` ABC; `HiddenMarkovRegimeModel` raises `RegimeModelNotImplemented`.
  - `market.py`: `market_regime("none")` ⇒ UNAVAILABLE.
  - `__init__.py`: `infer_regimes(financials, *, as_of, cfg)`.
- `src/vms/drivers/distributions.py` (DRIVER-DIST-1), `src/vms/drivers/walk_forward.py` (WF-1);
  `definitions.py` (per-driver year offsets, `refs`); `transforms.py` (numerically stable inverse; see "Bugs found").
- `src/vms/pipeline.py`: `run_estimation` / `Phase3Run`. `src/vms/cli/main.py`: `vms estimate`; demo also writes
  `state_posterior.json` and the Phase 3 `driver_diagnostics.json`; status `PHASE3_SMOKE_NOT_A_VALUATION`.
- `src/vms/schemas/config.py`, `config/default.yaml`: `regimes`, `estimation`, `walk_forward`;
  `config/driver_profiles/operating_company.yaml` v0.3.0 (`prior_scale` per driver).
- `src/vms/assumptions.py` + regenerated `docs/assumptions.md`: 14 Phase 3 IDs (REGIME-*, DRIVER-TRANSFORMS-v1,
  DRIVER-DIST-v1, DRIVER-FAMILY-v1, PRIORS-GLOBAL-v1, PARAM-UNCERTAINTY-BOOTSTRAP-v1, WALK-FORWARD-ORIGINS-v1,
  MODEL-SELECTION-WF-v1, DRIVER-DEPENDENCE-PHASE4-v1).
- `src/vms/__init__.py`: SCHEMA_VERSION `vms-0.1.phase3`.
- Tests (new):
  - `tests/unit/test_regimes.py` (21), `tests/property/test_regime_properties.py` (1 property, 300 examples)
  - `tests/unit/test_distributions.py` (37), `tests/unit/test_walk_forward.py` (6)
  - `tests/leakage/test_regime_leakage.py` (6), `tests/integration/test_cli_estimate.py` (5)
  - `tests/company.py` `cyclical_company` fixture (16 FY, growth/contraction cycles)
- Tests (updated): `tests/unit/test_config.py`, `test_package_skeleton.py`.
- Scripts: `scripts/leakage_mutation_check.sh` now uses literal multi-replacement mutations (6 mutations).
- Docs and CI: `README.md`, `docs/architecture.md`, `docs/data_contracts.md`, `.github/workflows/ci.yml` (`vms estimate` step).

## Tests run
- `pytest`: **392 passed** (76 new in Phase 3; 316 before): 86.6 s on the box (Python 3.13); clean clone + `uv venv --python 3.11` + `uv pip sync requirements.lock`: 392 passed in 94.3 s, demo + estimate exit 0, leakage 6/6 and invariant 7/7 KILLED.
- `scripts/leakage_mutation_check.sh`: **6/6 KILLED**:
  - 4 PIT-filter leaks;
  - walk-forward origin snapshot at t+400 d, with all guards removed;
  - regime inference fed a snapshot built at as_of+400 d.
- `scripts/invariant_mutation_check.sh`: **7/7 KILLED**.
- `vms demo --seed 42` and `vms estimate` on the synthetic dataset: exit 0.

## Acceptance criteria (§18 Phase 3), with evidence

1. **Fundamental and market regimes use distinct schemas.**
   - They are separate pydantic classes with `kind` Literal FUNDAMENTAL vs MARKET and `extra="forbid"`, and neither subclasses the other.
   - Cross-validation fails both ways, and an UNAVAILABLE market posterior cannot carry probabilities: `test_regimes.py::test_fundamental_and_market_schemas_distinct`.
   - Market is UNAVAILABLE when no source is configured (`market_regime_source: none`, MARKET-REGIME-UNAVAILABLE-v1). It is never derived from the fundamental state.
   - The CLI artifact persists both blocks with their kinds: `test_cli_estimate.py::test_estimate_artifacts_and_provenance`.

2. **No future-return labels in regime inference.**
   - The classifier is rule-based with no fitted labels. The only fitted object is the transition matrix, estimated from the classifier's own past posteriors.
   - `test_regime_leakage.py`:
     - `test_regime_code_cannot_reference_prices_or_returns`: an AST scan of `vms.regimes` finds no price/close/return/adjusted/volume identifiers, no `.market` access, and no imports of data/drivers/statements/quality.
     - `test_infer_regimes_signature_is_fundamentals_only`.
     - `test_prices_cannot_change_regimes_or_distributions` (hypothesis): random price rescaling leaves regimes, distributions and walk-forward byte-equal.
     - `test_future_prices_and_fundamentals_invisible`: a post-as_of price crash, a restatement and a new quarter change nothing; all `known_at ≤ as_of`.
     - `test_regimes_full_vs_known_only` (hypothesis over as_of, 2010–2026): full-load and known-only inputs give identical regimes.
     - `test_walk_forward_origin_unaffected_by_post_origin_mutation`.
   - Two mutation kills back this up: the walk-forward leak and the regime-inference leak.

3. **Posterior probabilities are finite, non-negative and sum to one within tolerance.**
   - Enforced by validators on every posterior type. `test_posterior_validator_rejects_invalid` covers NaN, negative and Σ≠1.
   - `test_regime_properties.py`: 300 hypothesis examples over feature sequences (including missing features), random rule parameters and state subsets. Every filtered, current and propagated posterior, and every transition row, is finite, ≥ 0 and sums to 1 within 1e-9.
   - CLI artifact: Σ = 1 checked for current and next-year.

4. **Sparse histories trigger shrinkage/fallback and low-confidence flags.**
   - `test_distributions.py::test_sparse_history_shrinks_and_flags[0,1,2]`:
     - n=0 gives PRIOR_FALLBACK, and the location and scale equal the prior.
     - n=1 and n=2 give SPARSE_HISTORY_SHRINKAGE + LOW_CONFIDENCE, with data weight n/(n+k) and the location strictly between the data median and the prior.
   - `test_shrinkage_weight_increases_with_history`; `test_long_history_not_low_confidence`.
   - Regime level: states below `min_regime_support` fall back to pooled (REGIME_POOLED_FALLBACK, REGIME_POOLED_FALLBACK_ALL): `test_regime_conditional_only_with_support`.
   - Empirical needs n ≥ 6 (EMPIRICAL_FALLBACK_TO_T); bootstrap with n < 2 becomes analytic_only (BOOTSTRAP_DEGENERATE_N_LT_2).
   - Transitions: PRIOR_DOMINATED_ROW, STATES_EXCEED_SUPPORT, NO_TRANSITIONS_OBSERVED_PRIOR_ONLY (`test_transitions_*`).
   - With no features, the current posterior is uniform with NO_FEATURES_UNIFORM_PRIOR + LOW_CONFIDENCE.

5. **Walk-forward diagnostics and parameter provenance are persisted.**
   - `state_posterior.json`: model id/version, config prior, per-period features (with snapshot `refs` and `known_at`) and posteriors with memberships, transitions with support counts, and per-origin regime Brier.
   - `driver_diagnostics.json`:
     - `distributions` (seed, bootstrap stream, estimation config, per-observation refs, priors, shrink weights, every spec's parameters, persisted bootstrap draws);
     - `walk_forward` (WF-1 protocol; per origin: origin_as_of, train_years, forecasts, realized value, pinball, coverage).
   - Evidence:
     - `test_cli_estimate.py::test_estimate_artifacts_and_provenance`;
     - `test_estimate_byte_reproducible_and_seed_sensitive` (same seed ⇒ identical bytes; different seed ⇒ different draws);
     - `test_distributions.py::test_provenance_refs_resolve_to_snapshot_records`;
     - `test_walk_forward.py::test_origins_past_only` (origin = first publication of FY y; train ≤ y; target y+1).
   - **Model selection never by in-sample fit alone:**
     - `test_selection_is_argmin_walk_forward_pinball` recomputes the selection from the per-origin scores.
     - `test_selection_never_in_sample` monkeypatches the in-sample scores to favour `prior_only`; selection is unchanged.
     - `test_too_few_origins_default_flagged`.

Also required by the task brief:
- **HMM:** interface only. `regimes.model: hmm` fails with `RegimeModelNotImplemented`, and `vms estimate` exits 2 (`test_estimate_hmm_not_implemented_exit_2`). It is not counted toward acceptance. Reason (REGIME-HMM-DEFERRED-v1): a 4-state Gaussian HMM on ≤ 10 annual / ≤ 40 overlapping quarterly observations per company is over-parameterised; a pooled panel HMM needs panel data.
- **Transforms:** logit for margins/rates, log1p for growth, identity for allocation ratios. `test_quantiles_within_bounds_and_monotone_for_every_driver` checks all 18 drivers with ±40 z outliers.
- **Exit codes:** unsupported profile gives 4; missing classification is BLOCKED (3).

## Walk-forward numbers (cyclical fixture, 16 FY, 13 origins, seed 42)
- Regime next-year Brier: transition model 0.268, persistence 0.351, uniform 0.404.
- Selected specs:
  - pooled_empirical: revenue_growth, ebit_margin, opex_ratio, payables, debt, cash;
  - pooled_t: tax rate, parent share;
  - regime_t: the rest.
- revenue_growth mean pinball: pooled_empirical 0.028 vs naive_last 0.046.
- **NAIVE_BENCHMARK_BETTER on 13/18 drivers.** All are ratios held constant in the synthetic fixture, where carrying the last value forward is exact. It is reported, not hidden.
- Central 80% interval coverage is 1.0 on those constant ratios, so the intervals are too wide when the true dispersion is zero. This is because of the prior_scale variance shrinkage.

## Bugs found while proving
- `transforms.inverse` raised `OverflowError` for extreme z: logit `exp(-z)` and log1p `expm1(z)`. A walk-forward with heavily mutated post-origin data reached it. Fixed with a stable sigmoid and a capped expm1 (results are clipped to bounds anyway). Regression test: `test_inverse_transforms_stable_at_extreme_z`.

## Known limitations
1. Regimes are quarterly/TTM when quarters exist, but drivers are annual. Driver observations take the state weights of the FY-end period.
2. Thresholds, transition prior, driver priors and prior_scale are global placeholders (PRIORS-GLOBAL-v1). There are no sector priors (needs panel data).
3. Real A-share histories (~10 FY) give few origins (≈ 5–7). With fewer than 3, selection falls back to `regime_t` with a flag. The synthetic demo has 1 origin.
4. Overlapping TTM features are autocorrelated. Quarterly transition pairs are weighted 1/4, but the support is still approximate.
5. The bootstrap understates parameter uncertainty at small n (flag below n=5). Regime and model uncertainty are reported but not yet propagated.
6. Driver dependence is not modelled (DRIVER-DEPENDENCE-PHASE4-v1). The deterministic central case still uses the Phase 2 medians, not the shrunk/selected locations.
7. Calibration: intervals over-cover on near-constant drivers, and the naive benchmark often wins on them.
8. Artifact size: the demo's driver_diagnostics.json is ≈ 0.5 MB, mostly persisted bootstrap draws and per-origin forecasts.
9. The full test suite now takes ≈ 87 s, up from ≈ 27 s; hypothesis-driven estimation tests dominate.

## New spec questions
1. Should the Phase 4 central case and sampler use the walk-forward-selected, shrunk distribution, replacing the Phase 2 median?
2. When the naive last-value benchmark beats every distributional spec, should selection allow a "persistence" spec (last value + shrunk dispersion)?
3. Is a quarterly regime clock with annual drivers acceptable for VMS-0.1, or should regimes be annual only?
4. Source of sector/industry priors (needs a cross-sectional panel): is that in scope for VMS-0.1?
5. What is the minimum origin count and target calibration (coverage tolerance) for the production gate?
