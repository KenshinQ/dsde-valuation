# Official VTP-0.1 Suite G — Market-pricing / exit-price separation

Date: 2026-11-27 Asia/Shanghai (CST, UTC+8)
Baseline: `origin/master` `dd84fc16f54c397d3ba88e953a384dfecd550466`
Tests PR: https://github.com/KenshinQ/dsde-valuation/pull/39
Tests head: `7fc9722b8fa31127b835573e8ba54d6ff165cb76`
Evidence branch: `cursor/vtp-0.1-evidence-11d5` (PR #33)
Production logic: **unchanged**

## Official name (do not use the old label)

Official VTP-0.1 Suite G is **Market-pricing / exit-price separation** (VTP-0.1.md, around L269):

- G-01 No implicit convergence
- G-02 Intrinsic value held fixed
- G-03 Market multiple held fixed
- G-04 Fundamental / market regime independence
- G-05 Explicit convergence scenario
- G-06 No future-price-as-intrinsic-ground-truth (this criterion is in official Suite G; included here)

The backlog and older verdicts called Suite G “Numerical Counterfactuals” and once put the 10×12×4 routing gap on G-01. That was a mislabel. Official routing is E-01 (backlog item 9), already recorded as **PARTIAL** on PR #38. This report does not reopen or substitute that matrix.

## Verdict

| Criterion | Status | Close evidence |
|-----------|--------|----------------|
| G-01 | **PASS** | Production `generate_exit_prices`, default `TERMINAL_MULTIPLE_DEFAULT` |
| G-02 | **PASS** | Same API; financial-path SHA-256 held fixed |
| G-03 | **PASS** | Same API; market posterior/config/seed held fixed |
| G-04 | **PASS** | Market-only + fundamental-only + default `NONE` / opt-in `CONFIGURED` |
| G-05 | **PASS** | Production `run_convergence_scenario` at rate 0.40 / blend 0.50 |
| G-06 | **PASS** | Production `run_evaluation` report labels + exit-bundle label |
| **Official Suite G** | **PASS** | All six official criteria have fresh, non-vacuous production evidence |

Repository labels are **unchanged**: `ENGINEERING_BLOCKED` / `RELEASE_BLOCKED` / `DO_NOT_MERGE` / `INVESTMENT_VALUE_NOT_ESTABLISHED`. Official Suite J remains **BLOCKED**. Official E-01 remains **PARTIAL**. This Suite G close does not authorize `ENGINEERING_ACCEPTED` or investment value, and does not start backlog items 11+ (full PIT / calibration / investment value).

## What is not close evidence

- `SimpleValuationModel` and `artifacts/vtp-0.1-evidence/suite_g_execution.log` (old log claimed G-01..G-05 PASS on a toy model with Intrinsic=14492.23 / Exit(compressed)=10687.35 / Exit(expanded)=17933.46). **Not used.**
- `tests/vtp_0_1/suite_g/` placeholders that `pytest.skip` (“数值实验待补”). Those files are not on `master` and were not used.
- `Suite_G_Market_Pricing_junit.xml` (2026-11-07, 13 passed on `test_phase9_acceptance.py` + `test_exit_price_properties.py`). Re-run below as **supporting only**.
- Hardened `NO_SILENT_INTRINSIC_COPY` / I-M05 / `default_forbids_intrinsic_copy`: **supporting only**. They cannot alone write official G-01–G-05 as PASS.
- Suite I 6/6 KILLED, A-02 isolation, item-6 offline E2E smoke, and the official E-01 10×12×4 matrix: **not substitutes** for this suite.

## Production APIs and experiment (predeclared)

Runner: `tests/evaluation/suite_g_production_counterfactuals.py` (must be invoked as `python -m tests.evaluation.suite_g_production_counterfactuals`).

- Paths: production `vms.pipeline.run_path_projection` on `tests.company` (years 2016–2024), `n_paths=24`, `n_years=3`, `seed=42`, policy `historical_continuation`.
- Paths A: `growth=0.05`. Paths B: `growth=0.12`.
- Exit: production `vms.market_pricing.generate_exit_prices`, horizon=1, metric=`ev_ebitda`, seed=42.
- Compressed market: fallback prior `COMPRESSED=1.0`, `state_scales.COMPRESSED=0.60`.
- Expanded market: fallback prior `EXPANDED=1.0`, `state_scales.EXPANDED=1.50`.
- Posterior: `estimate_market_pricing_state(use_fallback_when_unavailable=True)`.
- Sentinel intrinsic = `99999.0` (must be ignored on the default scenario).
- G-05: `run_convergence_scenario(..., stochastic_rate=0.40, blend_weight=0.50)`.
- Fail-closed: `n_valid==0` is BLOCKED, not PASS. `toy_model_used=false`.

Production source SHA-256 (unchanged; see `production_source_sha256.txt`):

- `src/vms/market_pricing/exit_prices.py` `6e05bacb0b0cfcf700dadd0c7a6e7a9baf70a4b106aaa30d889addf873e3365b`
- `src/vms/market_pricing/config.py` `7f6171b7bb1aab09955c1b49ee4adec6e288a2fdab753dd47c71dc56be3c6782`
- `src/vms/market_pricing/estimator.py` `59ad4b63b0ee88534edd36f4671588acd95024b3b4734f72bc172f73c41e182a`
- `src/vms/market_pricing/convergence.py` `a1f1076bfdbf860e9f9e845ef99ef4c40856112a5a712cd4ef1a363720ebe516`
- `src/vms/evaluation/metrics.py` `8b2e2f5ab53bd6bea781007837b7f998722d237c03a81e73b85227a0e0cbe65d`
- `src/vms/evaluation/rim_metrics.py` `bbbcb0100bb396bf4766787d6a3c639aff408621605e6a8fb9db949eccaf4f09`

## Commands and results

Full command text: `suite_g_official/COMMANDS.txt`.

### Official runner (G-01..G-05)

```
cd /workspace/dsde-valuation-suiteg
python -m tests.evaluation.suite_g_production_counterfactuals --out …/official
```

Exit 0. Started 2026-11-27T02:30:43+08:00, finished 2026-11-27T02:30:46+08:00 (Asia/Shanghai).

Artifact: `suite_g_official/official/suite_g_production_counterfactuals.json`
SHA-256: `3e7848584693f1ba4f8009b6c5ab48ebd2de64135ed0e53fcc8c28d0c925d323`

### Official pytest (G-01..G-06)

```
python -m pytest tests/evaluation/test_suite_g_official_counterfactuals.py -v --tb=short \
  --junitxml=…/Suite_G_Official_Counterfactuals_junit.xml
```

**6 passed in 2.97s**, exit 0. Python 3.13.5, pytest 9.2.0.

JUnit SHA-256: `238314b4a4be9659fe3b59e87212eda49637d2b5baf6b0f8000e6e15f0399e28`

### Supporting pytest (not official close)

```
cd /workspace/dsde-valuation
python -m pytest tests/unit/test_phase9_acceptance.py \
  tests/property/test_exit_price_properties.py \
  tests/unit/test_evaluation.py::test_targets_scored_separately_and_iv_not_price \
  tests/unit/test_phase11_acceptance.py::test_ac4_future_price_not_intrinsic_truth
```

**15 passed in 3.32s**, exit 0. Supporting only (phase-9 AC1/AC3/AC4/AC5, silent-copy properties, evaluation G-06 twins).

JUnit SHA-256: `5d541414389dd35e1829b0427646e84ea2b7cf1572f16b4c83ebdb8df7df43ac`

## Item evidence

### G-01 No implicit convergence — PASS

Fixed financial-path distribution (paths A) and a sentinel intrinsic map (`99999.0`). Only the market-pricing regime / multiple scale changed (compressed prior+scale vs expanded). Default scenario remains `TERMINAL_MULTIPLE_DEFAULT`.

| Side | n_valid | n_failed | mean exit | p50 |
|------|---------|----------|-----------|-----|
| Compressed | 24 | 0 | 1.1743403514237223 | 1.188458767102539 |
| Expanded | 24 | 0 | 2.672271750686516 | 2.720446439094365 |

- Exit distribution changed; not identical to the sentinel intrinsic.
- `silent_copy_of_sentinel`: none. `intrinsic_value_used` on the default scenario: false.
- `default_forbids_intrinsic_copy`: true. Bundle label: `FUTURE_MARKET_EXIT_PRICES`.
- Non-vacuous: 24/24 valid paths.

### G-02 Intrinsic value held fixed — PASS

Financial-path content SHA-256 was identical before and after both default-scenario exit generations:

`e3071243d031706786d77ca2f7608adb06af55503ffb5d676a0f1dacde4ee0e1`

The sentinel intrinsic map was also held fixed and was not used. Changing only the terminal-multiple regime (compressed → expanded) moved the exit mean from 1.1743403514237223 to 2.672271750686516.

### G-03 Market multiple held fixed — PASS

Same market posterior (SHA-256 `c87688c409757dfa5f58462319425b681b43f1c90fd6434b09f34e0d8eb87fc5`), same config (SHA-256 `92d433adeafa1497a920760b2ce31df7ca88ad08bb9a55c1f53cd86b893e3d82`), same seed. Financial paths A (`growth=0.05`) vs B (`growth=0.12`).

| Paths | n_valid | n_failed | mean exit | p50 |
|-------|---------|----------|-----------|-----|
| A (0.05) | 24 | 0 | 1.1743403514237223 | 1.188458767102539 |
| B (0.12) | 24 | 0 | 2.196179100645408 | 2.1478076411472733 |

Lineage on a valid path (`mc:0`) attributes the exit to `denominator_field=ebitda` (174.78203906556644) and `terminal_multiple=5.790558329292514` (`metric_id=ev_ebitda`). The market multiple side is held fixed; the change comes through projected financial metrics.

### G-04 Fundamental / market regime independence — PASS

- Market-only: financial-path hash unchanged; exit distribution changed (G-02).
- Fundamental-only: path hash A `e3071243…` ≠ path hash B `71acf2472e28f75c028ca7bdbb4096bd37ae86166cea5bf2de401715003356fc`; market posterior held fixed; exit changed through projected metrics (G-03).
- Default `dependence_on_fundamentals=NONE` on the posterior and on the default exit bundle.
- Coupling is opt-in only: `apply_configured_dependence(..., tilt={"GROWTH": {"EXPANDED": 2.0, "COMPRESSED": 0.5}})` sets `CONFIGURED` and flag `CONFIGURED_FUNDAMENTAL_DEPENDENCE`.
- `MARKET_PRICING_STATES` and `FUNDAMENTAL_STATES` are disjoint (re-asserted in the official test). Supporting: `test_ac1_market_estimator_ignores_fundamentals`.

### G-05 Explicit convergence scenario — PASS

- Default path: `scenario_kind=TERMINAL_MULTIPLE_DEFAULT`. `MarketPricingConfig.convergence.enabled` is false.
- Explicit path: `run_convergence_scenario(..., stochastic_rate=0.40, blend_weight=0.50)` → `CONVERGENCE_TO_INTRINSIC`, flags include `EXPLICIT_CONVERGENCE_SCENARIO`.
- Uncertainty (not the 0/1 extremes used alone in older AC3): 10 paths fired (`intrinsic_value_used`), 14 valid paths did not. n_valid=24, n_failed=0.
- Because the experiment uses a sentinel intrinsic of 99999.0 at blend 0.50, fired paths pull the bundle mean / p95 / max up (mean 20834.05506496515, max 50000.380618239506) while p50 stays near the unconverged market exit (1.4750568428778659). That is the labeled, parameterized scenario — not implicit default-path convergence.

### G-06 No future-price-as-intrinsic-ground-truth — PASS

- Exit bundles are labeled `FUTURE_MARKET_EXIT_PRICES`, not intrinsic ground truth.
- Fresh production `vms.evaluation.run_evaluation` on `config/universe.synthetic.yaml` (same contract as `test_ac4_future_price_not_intrinsic_truth`):
  - `scores_unbiased["intrinsic_value"]["price_mae_forbidden"] is True`
  - `market_price_association_only.label == "MARKET_PRICE_ASSOCIATION_NOT_INTRINSIC_GROUND_TRUTH"`
- This is official G-06 in this suite (EVAL-IV-NOT-PRICE-TRUTH-v1 / SPEC §17.2). Supporting twins: `test_targets_scored_separately_and_iv_not_price`, phase-11 AC4, R6 association label.

## Artifact SHA-256

See `suite_g_official/SHA256SUMS.txt` (generated after this report was written). Key payloads:

- `official/suite_g_production_counterfactuals.json` `3e7848584693f1ba4f8009b6c5ab48ebd2de64135ed0e53fcc8c28d0c925d323`
- `official/Suite_G_Official_Counterfactuals_junit.xml` `238314b4a4be9659fe3b59e87212eda49637d2b5baf6b0f8000e6e15f0399e28`
- `official/runner_stdout.txt` `99f5beeb6860976a43e0da14a5b63e62f9f08fdc3965a904a525910fce342504`
- `official/pytest_official_stdout.txt` `7e7cfc503b89125cf9204277c5cd02ab2fcc19dd72c5582ba8738591a2899dd0`
- `supporting/Suite_G_Supporting_phase9_property_eval_junit.xml` `5d541414389dd35e1829b0427646e84ea2b7cf1572f16b4c83ebdb8df7df43ac`

## Repo status (unchanged fail-closed)

- Official Suite G (this item, backlog #10): **PASS**
- Official Suite J: still **BLOCKED**
- Official E-01 routing truth table: still **PARTIAL**
- Repo: **ENGINEERING_BLOCKED / DO_NOT_MERGE / INVESTMENT_VALUE_NOT_ESTABLISHED**
- PRs #33–#39 remain unmerged. No Cloud Agent. No production change.
