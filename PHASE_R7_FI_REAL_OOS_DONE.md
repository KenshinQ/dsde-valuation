# R7 — Deposit-taking FI real OOS (HiThink/EM lean): DONE

Date: 2026-10-25 (Asia/Shanghai). Branch: `feat/r7-fi-real-oos` (from `6c365fd` / R6 merge).
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
Prior: `PHASE_R6_BANK_RIM_WF_DONE.md`. Pace: **r7-default** (user widget).

Status: **R7 acceptance criteria pass** (fi_real materialize + prefer_local/`--refresh` + calibrate-rim wire).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim `CALIBRATION_PASS`, `ENSEMBLE_CALIBRATED`, `INVESTMENT_VALUE_SUPPORTED`,
gate lift, 非银金融, schema bump, invent OEI, or lower `MIN_HIST_PB_POINTS` (=12).

## Design
- **Reuse R6 protocol**: chronological-only, freeze-before-test, forecast-before-outcome,
  separate targets, Track B MIN=12 SKIP, pit_complete=false → exclude from `scores_unbiased`,
  hard `CALIBRATION_INSUFFICIENT` + `INVESTMENT_VALUE_NOT_ESTABLISHED`.
- **New materialize path** (does not replace synthetic `bank_synthetic`):
  - Universe: `config/universe.fi_deposit_lean_real.yaml` (`data_label: HITHINK_EM_LEAN_FI`)
  - `evaluation/fi_real_panel.py` → subject hist depth + EM industry (local-first)
  - `UniverseConfig.fi_real` + `materialize_universe(..., prefer_local=)`
  - CLI: `vms calibrate-rim --universe ..._real.yaml` (+ optional `--refresh`)
- **Assumption**: `EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1`
- Legacy `industry.unsupported` / `vms value|project` gate **untouched**. SCHEMA remains `vms-0.2.phase12`.
- Synthetic R6 path (`universe.fi_deposit_lean.yaml`) **retained** for regression.

## Changed / added files
```
src/vms/evaluation/fi_real_panel.py              NEW HiThink/EM lean real panel
src/vms/providers/eastmoney/enrich.py           prefer_local ⇒ zero REST even on miss
src/vms/evaluation/universe.py                   fi_real block + prefer_local
src/vms/evaluation/rim_run.py                    prefer_local + REAL-OOS cites
src/vms/reporting/calibrate_rim_bundle.py        prefer_local + rest_calls guard
src/vms/cli/main.py                              calibrate-rim --refresh
src/vms/assumptions.py / docs/assumptions.md     EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1
docs/calibration_protocol.md                     R7 section
config/universe.fi_deposit_lean_real.yaml        NEW real lean universe
tests/unit/test_r7_fi_real_oos.py                NEW AC1–AC10 (needs local duckdb)
tests/unit/test_r7_fi_real_wiring.py             NEW always-on wiring mocks
tests/integration/test_cli_calibrate_rim_real.py NEW CLI smoke (needs local duckdb)
PHASE_R7_FI_REAL_OOS_DONE.md
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | data_label non-SYNTHETIC; not bank_synthetic | `test_ac1_*`; universe YAML |
| 2 | no --refresh → rest_calls==0 | `test_ac2_*`; `test_prefer_local_true_*`; CLI smoke |
| 3 | --refresh: upsert allowed; fail→local/empty; no invent OEI | `test_ac3_*`; `test_prefer_local_false_*` |
| 4 | chrono + forecast outcomes=null first | `test_ac4_*` |
| 5 | pit_complete=false ∉ scores_unbiased | `test_ac5_*` |
| 6 | Track B hist&lt;12 → SKIP (000001 honest) | `test_ac6_*` |
| 7 | MIN=12; no default pb | `test_ac7_*` |
| 8 | INSUFFICIENT + INVESTMENT_VALUE_NOT_ESTABLISHED | `test_ac8_*`; bundle guards |
| 9 | legacy UNSUPPORTED / sector lint | `test_ac9_*`; fi_real_panel sector lint |
| 10 | synthetic R6 still green + PHASE_R7 | `test_ac10_*`; this file |

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `pytest tests/unit/test_r7_fi_real_*.py tests/integration/test_cli_calibrate_rim_real.py` | **18 passed** |
| Repo `.venv` | R4/R5/R6 + sector lint + docs sync (regression) | **green** |
| CLI | `vms calibrate-rim --universe config/universe.fi_deposit_lean_real.yaml` (no `--refresh`) | `data_label=HITHINK_EM_LEAN_FI`; forecasts=15; pit_excluded=15; Track B skips=15 eligible=0; `rest_calls=0`; `CALIBRATION_INSUFFICIENT`; `INVESTMENT_VALUE_NOT_ESTABLISHED` |


## Arch gate (PR #7)
- **REQUEST_CHANGES B1 closed**: `fetch_bundle` aligned with enrich/R4/R5 — `prefer_local=True` miss ⇒ local empty + flags, **no** Recipe E / forced REST; `prefer_local=False` (`--refresh`) unchanged.
- SHOULD-FIX: empty-tmp zero-REST test; AC9/AC10 not hidden by module skipif; AC5 locks real `scores_unbiased`; `_count_rest` uses structured `rest_calls` (not `rest_notes` substrings).
## Known gaps (honest)
- `CALIBRATION_PASS` / `ENSEMBLE_CALIBRATED` intentionally **not** emitted on R7-default
  (pit_complete typically false under HiThink LATEST_ONLY; OOS still thin).
- SCHEMA_VERSION remains `vms-0.2.phase12`.
- Names with OEI &lt; 12 FY (e.g. 000001) still Track B SKIP — data hard stop.
- CI without box duckdb skips live AC tests; wiring mocks always run.

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — real-panel walk-forward ≠ investment advice.
