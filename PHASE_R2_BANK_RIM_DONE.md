# R2a→R2b — Deposit-taking FI RIM common equity + P2 distribution: DONE

Date: 2026-10-22 (Asia/Shanghai). Branch: `feat/r2-bank-rim-ab` (from `8e1c0f2` / R1).
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
Prior: `PHASE_R1_BANK_RIM_DONE.md`. Pace: **r2ab-default** (user widget).

Status: **R2a + R2b acceptance criteria pass**.
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim OOS calibration, ensemble, Track B returns, or P/B-ROE (R2c/R2d out of scope).

## Design
- **R2a**: default `equity_basis=common`:
  `common_equity_0 = total_equity − minority_interest − other_equity_instruments`.
  Common NI = `basic_eps × shares`. Dividends = sharebonus FY interim+final DPS × shares.
  Real OCI when present; missing OEI/EPS → INELIGIBLE. Goodwill sensitivity-only.
- **R2b**: primary NI policy P2 = ROE × beginning common equity; bootstrap ~10y PIT ROE
  history (fixed seed); ke grid `{0.08, 0.09, 0.10}`; P1 constant common NI as control.
- **Reject**: lifting `industry.unsupported`; changing legacy `vms value` / `vms project` gate;
  changing `total_equity` semantics on non-value-rim paths; ensemble.

## Changed / added files (high level)
```
src/vms/schemas/fields.py                 FIELDS-3 (+OEI/preferred/perpetual/OCI/EPS/interest)
src/vms/assumptions.py                    EM-FI-F10-v1, RIM-COMMON-EQUITY-v1, RIM-NI-P2-ROE-v1,
                                          RIM-DPS-SHAREBONUS-v1, RIM-KE-GRID-v1
src/vms/providers/eastmoney/bank_f10.py   NEW mapper (companyType=3, NOTICE-aligned)
src/vms/providers/eastmoney/client.py     fetch_*_bank_f10*
src/vms/providers/eastmoney/store.py      em_bank_f10 DuckDB cache
src/vms/providers/eastmoney/enrich.py     enable_bank_f10 (label from YAML; no sector scatter)
src/vms/providers/eastmoney/industry.py   deposit_taking_fi_sw_label()
src/vms/methods/rim/from_snapshot.py      common equity bridge + DPS + EPS NI
src/vms/methods/rim/distribution.py       NEW P2 ROE bootstrap + ke grid
src/vms/reporting/value_rim_bundle.py     rim_distribution.json + summary percentiles
src/vms/cli/main.py                       --equity-basis/--paths/--seed/--ke-grid/--no-distribution
tests/unit/providers/test_bank_f10.py
tests/unit/methods/test_rim_r2_*.py
tests/integration/test_cli_value_rim.py   R2 path
docs/assumptions.md / data_contracts.md
PHASE_R2_BANK_RIM_DONE.md
```

R1 tests pin `equity_basis="total"` so legacy total-equity semantics stay covered.

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `python -m pytest` | **709 passed**, 2 skipped |
| Ingest | `vms ingest-hithink --ticker 000001.SZ --out /tmp/vms_000001 --prefer-local` | n_financial=667; bank_f10 mapped=99 |
| Smoke | `vms value-rim ... --out /tmp/vms_000001_rim_r2 --paths 200 --seed 42 --ke-grid 0.08,0.09,0.10` | VALID; see below |
| Legacy | `vms project` / `vms value` on bank industry | still exit **4** UNSUPPORTED_PROFILE (unchanged) |

## Acceptance → evidence

### R2a
| # | Criterion | Evidence |
|---|---|---|
| 1 | EM F10 companyType=3 NOTICE-aligned lines | `bank_f10.py` + ingest diag `bank_f10.mapped=99` |
| 2 | `common_equity_0` = 424,894,000,000 | smoke + `test_ac_common_equity_0_matches_000001_fy24` |
| 3 | NI primary = basic_eps × shares | smoke last_fy_ni=41,722,724,125.7; flag `NI_FROM_BASIC_EPS_TIMES_SHARES` |
| 4 | DPS from em_sharebonus = 0.608 | smoke + unit test |
| 5 | Real OCI; missing OEI/EPS → INELIGIBLE | unit tests; smoke flag `OCI_CONSTANT_LAST_FY_ASSUMPTION` |
| 6 | 600036 MI/OEI exclusion shape | common-equity formula TE−MI−OEI (fixture/unit) |
| 7 | Goodwill sensitivity only | `GOODWILL_SENSITIVITY_AVAILABLE`; not subtracted from book_equity_0 |
| 8 | R1 pins `equity_basis="total"` | `test_rim_from_snapshot` / `test_r1_bank_rim_acceptance` |

### R2b
| # | Criterion | Evidence |
|---|---|---|
| 1 | P2 primary; P1 control | `rim_distribution.json`; `p1_control_vps` |
| 2 | ROE ~10y PIT; p05<p50<p95; fixed seed | unit + smoke seed=42 |
| 3 | ke grid {0.08,0.09,0.10} | smoke ke_grid length 3 |
| 4 | No ensemble / R2c / R2d | `ensemble: null`; `NO_ENSEMBLE` flag |

## Smoke numbers (000001.SZ @ 2025-06-30, Asia/Shanghai)
Engineering only — **not** investment value.

| metric | value |
|---|---|
| common_equity_0 | **424,894,000,000** |
| total_equity_0 | 494,842,000,000 |
| goodwill_0 | 7,568,000,000 |
| last_fy_dps | **0.608** |
| last_fy_ni (EPS×shares) | 41,722,724,125.7 |
| P1 point VPS (w/ OCI const) | ≈19.25 |
| P1 control VPS (dist, no OCI) | ≈**21.24** |
| P2 VPS ke=0.08 p05/p50/p95 | 31.80 / **43.52** / 53.97 |
| P2 VPS ke=0.10 p05/p50/p95 | 21.72 / **29.49** / 36.43 |
| rim_status | VALID |
| investment_value | INVESTMENT_VALUE_NOT_ESTABLISHED |
| pit_complete | false (HiThink LATEST_ONLY) |

R1 VPS 25.44 (total equity / mixed CF div) intentionally superseded on common path.

## Known gaps (honest)
- Net issuance still zeros_explicit (no live issuance series).
- Industry-aux profile may remain low_confidence.
- ke/g from config WACC ASSUMPTIONs (not live PIT curve).
- SCHEMA_VERSION remains `vms-0.2.phase12`.
- R2c (P/B-ROE peers) / R2d (Track B returns) not started.

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — engineering smoke ≠ investment advice.
