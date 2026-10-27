# Phase R12 — calibrate-rim forecast → MethodDistribution: DONE

Date: 2026-10-27 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/calibrate-rim-md`. Prior: [PHASE_R9_LIVE_MD_ADAPTER_DONE.md](PHASE_R9_LIVE_MD_ADAPTER_DONE.md),
[PHASE_R8_PRIOR_ONLY_FI_DONE.md](PHASE_R8_PRIOR_ONLY_FI_DONE.md).
Baseline: master @ `75054ff` (R6 smoke golden).

Status: **R12 calibrate-rim forecast → MethodDistribution adapter accepted** for
research PRIOR_ONLY path only. Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
**Not** investment advice. **No** `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` /
`INVESTMENT_VALUE_SUPPORTED`. Does **not** claim calibrated production ensemble.
SCHEMA stays `vms-0.2.phase12`; package `0.2.0rc1`.

## Scope
Ingest **one** `vms calibrate-rim` forecast blob
(`forecasts/<instrument>/<YYYY-MM-DD>_hN.json`) into `list[MethodDistribution]`
for existing `build_prior_only_fi_bundle(components=...)`. Parallel to R9
`value-rim` ingest — does not change R9/`--from-value-rim` semantics. Closes the
R8 residual half for calibrate-rim forecast blobs.

## Changed / added files
```
src/vms/reporting/fi_method_distribution_adapter.py   + adapt_calibrate_rim_forecast / resolve_*
src/vms/reporting/prior_only_fi_bundle.py             calibrate_rim source_meta / assumption / warnings
src/vms/cli/main.py                                   --from-calibrate-rim-forecast (+ convenience)
src/vms/assumptions.py                                ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1
docs/assumptions.md                                   regenerated
docs/calibration_protocol.md                          R12 section
PHASE_R8_PRIOR_ONLY_FI_DONE.md                        residual: calibrate-rim half CLOSED
tests/fixtures/calibrate_rim_forecast_*.json          trimmed real-shape blobs
tests/unit/test_r12_calibrate_rim_md.py               AC1–AC4, AC6
tests/integration/test_cli_prior_only_fi_r12.py       AC5, AC7
PHASE_R12_CALIBRATE_RIM_MD_DONE.md                    this file
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | Fixture forecast (Track A VALID + Track B hist&lt;12 SKIP) → research PRIOR_ONLY; calibrated_claim=false; source=calibrate_rim; samples_from_point; synthetic=false | `test_ac1_*` |
| 2 | Same components production intent → mixture null | `test_ac2_*` |
| 3 | hist_n≥12 + median_pb only → Track B SKIP TRACK_B_CENTER_NOT_PER_SHARE; not in weights; median_pb audit only | `test_ac3_*` |
| 4 | No Track A / bad JSON / DIR 0 or ambiguous → fail closed | `test_ac4_*` |
| 5 | Without `--from-calibrate-rim*`, R8 demo + R9 `--from-value-rim` unchanged | CLI regression |
| 6 | SCHEMA=`vms-0.2.phase12`; package=`0.2.0rc1`; forbid PASS labels; MIN=12 | `test_ac6_*` |
| 7 | CLI smoke `--from-calibrate-rim-forecast` writes PRIOR_ONLY bundle + data_label / source cite | CLI smoke |

## Centers / SKIP (pinned)
- Track A: `forecasts.intrinsic_value.point` (VALID + finite positive) else `baselines.central_rim.vps`
- pb_common: **not produced**
- Track B: no PER_SHARE exit on blob → weight-side always SKIP when `track_b` present;
  `TRACK_B_CENTER_NOT_PER_SHARE` when hist≥MIN; preserve blob skip_reason when hist&lt;MIN
  (never default `NOT_ASSESSED` → `HIST_PB_BELOW_MIN`)
- Samples: `samples_from_point` only; `synthetic=false`; `source=calibrate_rim`

## Hard constraints honored
- Never emit `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`
- Production `intent=production` refuses mixture
- Never feed `median_pb` × book/spot as PER_SHARE
- Do not rewrite calibrate-rim / rim_run / rim_forecast to invent exit VPS
- Do not lower `MIN_HIST_PB_POINTS` (=12); do not invent OEI; do not lift 非银
- Do not aggregate multi-origin blobs into one mixture
- R9 `--from-value-rim` semantics unchanged; SCHEMA/package unchanged

## Honest notes
- calibrate-rim blob has no `pb_common` / exit VPS → typically **one** eligible
  method (Track A). Ensemble ≥2-eligible gate then refuses a numeric mixture
  (`research_mixture=false`), same as R8 `track_a_only`. Path remains labeled
  `PRIOR_ONLY` / `calibrated_claim=false` / `INVESTMENT_VALUE_NOT_ESTABLISHED`.
- `sanitize_injected_components` preserves already-SKIP Track B `skip_reason`
  (does not wipe `TRACK_B_CENTER_NOT_PER_SHARE` / blob reasons into inject labels).

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — calibrate-rim forecast → PRIOR_ONLY ingest
≠ investment advice ≠ `ENSEMBLE_CALIBRATED`.
