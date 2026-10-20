# Phase 4 — Correlated path sampler: DONE

Scope: SPEC §8.2–8.3, §18 Phase 4, plus Phase 3 review decisions (persistence_t, eval gates, central-from-selected,
regime-clock / industry-priors notes) and the Phase 6 WACC owner decision (recorded only).

Not started: Phase 5 (path-wise statements / capital allocation).

## Decisions recorded (docs/assumptions.md)
| ID | Decision |
|---|---|
| CENTRAL-FROM-SELECTED-v1 | Phase 4 central + sampling use WF-selected shrunk distributions |
| MODEL-SELECTION-WF-v2 (supersedes v1) | Adds selectable `persistence_t` (last value + shrunk dispersion); `naive_last` remains a non-selectable point benchmark; LOW_EVAL_SUPPORT + COVERAGE_MISCALIBRATED gates |
| REGIME-CLOCK-MISMATCH-v1 | Keep quarterly regime + annual drivers; annual-only deferred |
| INDUSTRY-PRIORS-DEFER-v1 | Industry priors out of VMS-0.1; global priors + shrinkage |
| PATH-SAMPLER-v1 / PATH-CONSTRAINTS-v1 / DRIVER-DEPENDENCE-v1 | Sampler contract, bounds/repairs, Gaussian-copula shrunk correlations |
| WACC-INPUTS-v1 (supersedes DEFERRED) | RF = 10y CGB at as_of (PIT); ERP 6% default (swept); beta vs CSI 300, 2y weekly, shrink toward 1 |

Config: `estimation.walk_forward.coverage_tolerance: 0.15`; `monte_carlo.correlation_prior_strength / min_correlation_years / artifact_path_cap`.

## Changed / new files
- `src/vms/sampling/` (was empty stub): `schemas.py`, `dependence.py`, `simulate.py`, `__init__.py`
- `src/vms/engine.py` — `ValuationEngine` facade (`simulate_paths` live; valuation methods raise Phase 6+)
- `src/vms/pipeline.py` — `Phase4Run`, `run_simulation`, `_central_from_selected`
- `src/vms/drivers/distributions.py` — `persistence_t` in SPECS; cite MODEL-SELECTION-WF-v2
- `src/vms/drivers/walk_forward.py` — LOW_EVAL_SUPPORT, COVERAGE_MISCALIBRATED
- `src/vms/drivers/estimate.py` — `selected_median` method
- `src/vms/schemas/config.py`, `config/default.yaml` — MC correlation knobs, coverage_tolerance
- `src/vms/cli/main.py` — `vms simulate`; demo writes SimulationBundle; SMOKE `PHASE4_SMOKE_NOT_A_VALUATION`
- `src/vms/assumptions.py` + regenerated `docs/assumptions.md`
- `src/vms/__init__.py` — schema `vms-0.1.phase4`
- Tests: `tests/unit/test_sampling.py` (10), `test_persistence_and_gates.py` (3), `tests/integration/test_cli_simulate.py` (3)
- Docs/CI: README, architecture, data_contracts, `.github/workflows/ci.yml`

## Tests run
- **407 passed** (~120 s, Python 3.13 box). New Phase 4-related: 16 tests (plus persistence/gates).
- Leakage mutation: **6/6 KILLED**. Invariant mutation: **7/7 KILLED**.
- `vms demo` / `vms simulate` exit 0 on synthetic data.

## Acceptance criteria (§18 Phase 4)

1. **Fixed seed reproduces paths.**
   - `test_sampling.py::test_fixed_seed_reproduces_paths`: identical seed ⇒ identical `SimulationBundle` dump; different seed ⇒ different year-1 drivers; `repeated_seed_stable is True`.
   - `test_cli_simulate.py::test_simulate_seed_reproducible`: byte-identical `simulation_bundle.json` for seed=9, different for seed=10.
   - Streams: `param_bootstrap:<driver>` (Phase 3) and `path:<i>` (Phase 4); PCG64 SeedSequence (SPEC §8.3).

2. **Material driver dependence is not silently ignored.**
   - Dependence method `gaussian_copula_shrunk_pearson` with explicit shrink toward I; material blocks DEMAND_PROFIT / WORKING_CAPITAL / REINVESTMENT / CAPITAL always jointly drawn (DRIVER-DEPENDENCE-v1).
   - `test_material_dependence_not_silently_ignored`, `test_shrink_correlation_toward_identity`, `test_gaussian_copula_unit` (|corr| > 0.5 under ρ=0.8).
   - Sparse overlap ⇒ `CORRELATION_SPARSE_HEAVY_SHRINK` / `CORRELATION_IDENTITY_FALLBACK` (flagged, never silent independent sampling of known blocks).
   - Cyclical fixture: 9 overlap years, shrink weight ≈ 0.64.

3. **Bounds/constraints are explicit.**
   - PATH-CONSTRAINTS-v1: clip to profile bounds; soft repair `ebit_margin ≤ gross_margin` (MARGIN_ORDER_REPAIRED); hard rejects listed in INVALID_REASON_CODES.
   - `test_bounds_and_constraints_explicit`: every valid path-year respects bounds and margin order.

4. **Invalid-path reasons are reported.**
   - `InvalidPathSummary(reason, year_index, detail)` aggregated in `diagnostics.invalid_by_reason`.
   - `test_invalid_path_reasons_reported`: reason set ⊆ INVALID_REASON_CODES; valid+invalid = n_paths.
   - Fraction > `max_invalid_path_fraction` ⇒ flag INVALID_PATH_FRACTION_EXCEEDED (CLI exit 5).

5. **Synthetic-distribution tests and Monte Carlo stability diagnostics pass.**
   - Copula unit test; shrink unit test; MCSE / p05/p50/p95 in `key_statistics`; seed-stability check inside `simulate_paths`.
   - Provenance: data_hash, config_hash, code_version, parameter_snapshot (selected specs, dependence/transitions/posterior hashes), path IDs `mc:<i>` / `central`.
   - Facade: `ValuationEngine.simulate_paths` returns the bundle; `value_paths` raises NotImplementedError (Phase 6).

Also from Phase 3 review (implemented now):
- **persistence_t** selectable: cyclical fixture selected Counter `{persistence_t: 7, regime_t: 6, pooled_empirical: 3, pooled_t: 2}`.
- **LOW_EVAL_SUPPORT** when origins < 3 (with low_confidence).
- **COVERAGE_MISCALIBRATED**: 13/18 drivers on the cyclical fixture (constant ratios → empirical coverage 1.0 > 0.95). Flagged, not hidden.

## Known limitations
1. Dependence is pooled residual correlation + Gaussian copula, not a full regime-conditional block bootstrap of residual vectors (regime overrides empty; needs more overlap per state).
2. Parameter draws are independent across drivers (bootstrap indices not coupled); process shocks carry the cross-driver dependence.
3. `persistence_t` is AR(1) with ρ=1 in transformed space plus shrunk noise — not a mean-reverting OU.
4. Central state path is greedy argmax through the mean transition matrix (no blending of soft states).
5. Demo/simulate embed at most 500 paths in JSON; fuller history goes to `paths.parquet`.
6. Path-wise accounting statements are Phase 5 — SimulationBundle drivers are not yet projected to FCFF.
7. Suite runtime ≈ 2 min (demo now runs up to 500 paths).

## New questions
1. Should parameter-bootstrap indices be coupled across drivers (one global draw index) so parameter uncertainty is also correlated?
2. Prefer residual block-bootstrap (when n_overlap ≥ ?) over the Gaussian copula as the default dependence method?
3. Production gate: should INVALID_PATH_FRACTION_EXCEEDED block the run (exit 5) or only warn?
4. When COVERAGE_MISCALIBRATED fires on near-constant drivers, auto-prefer persistence_t even if pinball is close?
