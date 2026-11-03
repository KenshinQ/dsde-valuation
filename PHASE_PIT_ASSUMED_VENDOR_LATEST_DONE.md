# PHASE DONE: PIT_ASSUMED / VENDOR_LATEST_AS_OF research scoring

Date: 2026-11-04 Asia/Shanghai  
Repo: KenshinQ/dsde-valuation  
Base: master `8fb1c40` / SCHEMA `vms-0.2.phase12` / package `0.2.0rc1`

## Boundary

- Declared `LATEST_ONLY` vendor panels are research-usable under explicit
  `pit_policy=PIT_ASSUMED` / `VENDOR_LATEST_AS_OF`.
- NOTICE_DATE still gates availability; `pit_complete` stays **false** (never claim FULL_HISTORY).
- Research `scores_unbiased` may include PIT_ASSUMED origins.
- HARD: never `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` from this alone;
  keep `INVESTMENT_VALUE_NOT_ESTABLISHED`; PASS-claim uses **strict** `n_unbiased_pit_complete`.
- No live trading; no invent OEI / default PB; no SCHEMA/package bump.

## AC

1. LATEST_ONLY + declared sources → `pit_policy=PIT_ASSUMED` (not blanket exclude as PIT_INCOMPLETE).
2. Research scores can be produced under assumption; undeclared/UNKNOWN still excluded.
3. PASS still impossible without authorized pass-claim **and** strict pit_complete depth.
4. Assumptions: `PIT-ASSUMED-VENDOR-LATEST-v1`, `PIT-INCOMPLETE-v2` (supersedes v1),
   `HITHINK-LATEST-ONLY-v2` (supersedes v1); docs regenerated.
5. Unit/smoke coverage for classifier + research filter + R6/R7 expectations.

## Key files

- `src/vms/pit/policy.py` (new)
- `src/vms/evaluation/run.py`, `rim_run.py`
- `src/vms/assumptions.py` + `docs/assumptions.md`
- `src/vms/reporting/calibrate_mature_bundle.py`, `calibrate_rim_bundle.py`
- `docs/calibration_protocol.md`, `docs/data_contracts.md`
