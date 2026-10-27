# Calibration protocol (VMS-0.2)

Implements SPEC §17. Engineering metrics ≠ investment alpha.

## Walk-forward (required)

At each historical decision timestamp:

1. Reconstruct the PIT information set and contemporaneous peer universe.
2. Fit/update drivers, states, peers and parameters **only** on permitted past data.
3. **Persist forecasts before reading outcomes** (`persisted_before_outcomes=true`).
4. Evaluate only after the target horizon / accounting period matures.
5. Repeat chronologically. **No** random row-level time-series splits.

CLI: `vms evaluate` / `vms phase11`.

## Separate evaluation targets

Score independently (never conflate):

- operating / cash-flow forecasts;
- relative / peer multiple behavior;
- asset NAV inputs where later observable;
- **future market prices** (not intrinsic ground truth);
- total-return distributions and loss probabilities;
- ensemble calibration **only** for its predeclared target.

Future market price **must not** be treated as intrinsic-value ground truth (`EVAL-IV-NOT-PRICE-TRUTH-v1`).

## Baselines

Include where data allow: historical driver median; central-case DCF (eligible profiles); simple multiple; no-regime; current-multiple persistence (exit); profile-appropriate benchmarks. Document unavailable baselines.

## Release gates (SPEC §17.4)

A calibration method or ensemble is production-eligible only when:

- target predeclared;
- sufficient OOS data (or justified hierarchical pooling);
- metrics vs baselines with subgroup diagnostics;
- no material leakage;
- weights/hyperparameters frozen before the test window;
- subgroup instability reported.

Otherwise mark `CALIBRATION_INSUFFICIENT` and keep method-specific distributions.

| Status | Synthetic `0.2.0rc1` |
|---|---|
| `ENGINEERING_PASS` | Yes |
| `CALIBRATION_PASS` | No → `CALIBRATION_INSUFFICIENT` |
| `ENSEMBLE_CALIBRATED` | No |
| `INVESTMENT_VALUE_NOT_ESTABLISHED` | Yes |
| `INVESTMENT_VALUE_SUPPORTED` | **Forbidden** without separate OOS research protocol |

## Weight freeze

`freeze_weights_before_test` / `assert_weights_unchanged` — mutation after freeze fails closed (`ENSEMBLE_WEIGHTS_MUTATED_AFTER_FREEZE`).

## Bank RIM walk-forward (R6)

Deposit-taking FI lean curated universe (`config/universe.fi_deposit_lean.yaml`).

CLI: `vms calibrate-rim` (does **not** replace synthetic `vms phase11`).

At each chronological origin:

1. Reconstruct PIT; build RIM Track A forecast (driver ROE + intrinsic VPS) + FI baselines.
2. Persist forecast with `outcomes=null` and `persisted_before_outcomes=true`.
3. Assess Track B eligibility: own-hist common P/B `n >= MIN_HIST_PB_POINTS` (=12); else **SKIP** (no invent OEI).
4. After horizon matures, attach outcomes (driver ROE, later-origin VPS stability, market association).
5. Score targets separately. `pit_complete=false` excluded from `scores_unbiased`.

Assumption: `EVAL-RIM-FI-DEPOSIT-WF-v1`. Expected on R6-default: `CALIBRATION_INSUFFICIENT` + `INVESTMENT_VALUE_NOT_ESTABLISHED`. Schema stays `vms-0.2.phase12` — do not bump schema to claim PASS.

CI locks default lean **synthetic** smoke counts (`G_*` in `tests/integration/test_cli_calibrate_rim.py`) as an **engineering golden** (protocol regression). That golden is **not** `CALIBRATION_PASS` and does **not** cover R7 real-OOS counts.

## Deposit-taking FI real OOS (R7)

Lean curated HiThink + EM panel (`config/universe.fi_deposit_lean_real.yaml`).

CLI: `vms calibrate-rim --universe config/universe.fi_deposit_lean_real.yaml`
(default remains R6 synthetic lean). Optional `--refresh` allows Recipe E / EM REST;
without it, materialize is local-first with **zero REST**.

Inherits R6 protocol gates. Assumption: `EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1`.
Expected on R7-default: `CALIBRATION_INSUFFICIENT` + `INVESTMENT_VALUE_NOT_ESTABLISHED`
(engineering success ≠ calibration PASS). Schema stays `vms-0.2.phase12`.

## FI PRIOR_ONLY research ensemble wiring (R8)

Wires deposit-taking FI RIM method distributions into Phase 8
`build_ensemble(intent=research_prior)` for a labeled research mixture.

CLI: `vms prior-only-fi` (does **not** replace synthetic `vms phase8`).

- Track A `residual_income` required; `pb_common` optional when valid.
- Track B `rim_track_b_exit` enters weights **only** when `hist_n >= MIN_HIST_PB_POINTS` (=12);
  else honest SKIP (no invent OEI / no default pb=2.0).
- Production intent on the same components refuses mixture.
- Hard labels: `PRIOR_ONLY` / `ENSEMBLE_UNCALIBRATED` / `CALIBRATION_INSUFFICIENT` /
  `INVESTMENT_VALUE_NOT_ESTABLISHED`. Never `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` /
  `INVESTMENT_VALUE_SUPPORTED`.
- Does not lift `industry.unsupported` / 非银金融. Schema stays `vms-0.2.phase12`.

Assumption: `ENSEMBLE-PRIOR-ONLY-FI-v1`.

## Live MethodDistribution adapter (R9)

Ingests a single-ticket `vms value-rim` out directory into
`MethodDistribution[]` for the existing R8 PRIOR_ONLY research path.

CLI: `vms prior-only-fi --from-value-rim DIR` (mutually exclusive with `--scenario`;
does **not** replace synthetic `vms phase8` or the R8 demo scenarios).

- Track A center: `method_result.values.value_per_share` preferred; else
  `rim_distribution.ke_grid[0].vps_p50`.
- Optional `pb_common`: `rim_pb_roe.relative_vps` when ok.
- Track B: `hist_n` from `rim_track_b.hist_pb.n`. **PER_SHARE** center prefers
  `rim_track_b.exit_prices.summaries[<horizon>].p50` (exit_price_per_share median;
  first finite horizon in numeric key order) or an explicit `exit_vps_center`.
  `rim_track_b.pb_center_used` is an own-hist **P/B multiple** kept for audit only
  and is **never** fed as PER_SHARE into mixture weights
  (`TRACK_B_CENTER_NOT_PER_SHARE` when `hist_n >= MIN` and no mapped VPS).
  Enters weights only when `hist_n >= MIN_HIST_PB_POINTS` (=12) **and** a mapped
  PER_SHARE center is present; else honest SKIP.
- Samples (R9 minimal slice): `samples_from_point(center)`;
  `diagnostics.synthetic=false` + `sample_generation=samples_from_point` +
  source artifact paths. R10 prefers persisted path samples when present
  (`ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1`).
- Production intent on the same components refuses mixture.
- Hard labels unchanged: `PRIOR_ONLY` / `ENSEMBLE_UNCALIBRATED` /
  `CALIBRATION_INSUFFICIENT` / `INVESTMENT_VALUE_NOT_ESTABLISHED`.
  Never `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.
- `calibrate-rim` is **not** primary mixture input.
- Schema stays `vms-0.2.phase12`; package `0.2.0rc1`.

Assumption: `ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1` (extends `ENSEMBLE-PRIOR-ONLY-FI-v1`).


## Live sample paths (R10)

Extends R9 live MethodDistribution adapter: prefer **path-level samples**
persisted by `vms value-rim` instead of always `samples_from_point(center)`.

- Persist (value-rim write):
  - Track A `rim_distribution.json`: primary ke cell
    `vps_samples: float[]` + `n_vps_samples` (capped, default 96); percentiles kept.
  - Track B `rim_track_b.json` → `exit_prices.summaries[<h>]`:
    `exit_vps_samples` + `n_exit_vps_samples` (valid `exit_price_per_share`);
    summaries / p50 unchanged.
- Adapter (read): prefer live arrays when present (len ≥ 1) →
  `sample_generation=live_paths`, `diagnostics.synthetic=false`,
  `n_live_samples` + source artifact paths. Missing → R9 compat
  `samples_from_point` stamp (legacy out-dirs keep working).
- Optional `pb_common` may stay `samples_from_point` when only a point
  `relative_vps` exists (no invented ROE path bank in R10).
- Track B center rules unchanged (exit VPS PER_SHARE; `pb_center_used` audit-only).
- Production intent still refuses mixture. Hard labels unchanged.
  Never `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.
- `calibrate-rim` is **not** primary mixture input.
- Schema stays `vms-0.2.phase12`; package `0.2.0rc1`.
- **Prefix-cap:** CLOSED by R11 deterministic stride subsample
  (`ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1`). When `n_valid > 96`,
  persisted samples use systematic indices
  `sorted({(i·n)//cap for i in range(cap)})` (defensive fill if needed);
  when `n_valid <= 96`, retain all finite-positive. Track A/B collect the full
  finite-positive bank first, then subsample (no early-break prefix).
  Full-set percentiles remain on the artifact. **Subsample ≠ calibration coverage.**

Assumption: `ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1`
(extends `ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1`).
Cap policy (new writes): `ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1`.


## Live sample stride cap (R11)

Closes R10 prefix-cap known gap. Same schema/package; research PRIOR_ONLY only.

- Algorithm: deterministic stride (`subsample_cap` / `stride_cap_indices`);
  no extra RNG. Output keeps relative path order.
- Cap default remains `LIVE_SAMPLE_CAP=96`; no uncapped dumps.
- Full-set p05/p50/p95 unchanged (computed before cap).
- Never `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.
- Adapter read semantics unchanged (prefer live arrays → `live_paths`).

Assumption: `ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-STRIDE-CAP-v1`
(extends `ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1`).


## calibrate-rim forecast → MethodDistribution (R12)

Closes the R8 residual half for **calibrate-rim forecast blobs** (R9 already closed
the `value-rim` half). Research PRIOR_ONLY ingest only — **not**
`ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS`.

CLI (canonical): `vms prior-only-fi --from-calibrate-rim-forecast PATH`
where `PATH` is one `forecasts/<instrument>/<YYYY-MM-DD>_hN.json`.

Convenience: `vms prior-only-fi --from-calibrate-rim DIR --instrument ID --origin-as-of DATE`
resolves `DIR/forecasts/<ID>/<DATE>_h*.json`; **0 or >1 match → fail closed**
(never silently pick "latest"). Mutually exclusive with `--from-value-rim` /
`--scenario`.

- Track A center: `forecasts.intrinsic_value.point` when `status=VALID` and finite
  positive; else `baselines.central_rim.vps`. Missing → fail closed.
- **No** `pb_common` (blob has no `relative_vps`; never invent from ROE/spot).
- Track B: ledger from `track_b.hist_n` / `skip_reason` / `median_pb`.
  `median_pb` is an own-hist **P/B multiple** (audit only) and is **never** a
  PER_SHARE weight center. Even when `hist_n >= MIN_HIST_PB_POINTS` (=12) /
  blob `status=ELIGIBLE`, Track B **SKIP** `TRACK_B_CENTER_NOT_PER_SHARE`
  (ELIGIBLE hist depth ≠ PER_SHARE exit VPS). `hist_n < MIN` → SKIP (preserve
  blob `skip_reason` when explicit SKIP; never default `NOT_ASSESSED` to
  `HIST_PB_BELOW_MIN`).
- Samples: `samples_from_point(center)` only; `diagnostics.synthetic=false` +
  `sample_generation=samples_from_point` + `source=calibrate_rim` + blob path.
- One blob per ingest — does **not** aggregate multi-origin forecasts into one
  mixture (that would look like a calibrated ensemble).
- Does **not** rewrite calibrate-rim emitters to invent exit VPS; does not lower
  MIN; does not invent OEI; does not change R9 `--from-value-rim` semantics.
- Hard labels unchanged: `PRIOR_ONLY` / `ENSEMBLE_UNCALIBRATED` /
  `CALIBRATION_INSUFFICIENT` / `INVESTMENT_VALUE_NOT_ESTABLISHED`.
  Never `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.
- Schema stays `vms-0.2.phase12`; package `0.2.0rc1`.

Assumption: `ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1`
(extends `ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1` / `ENSEMBLE-PRIOR-ONLY-FI-v1`).

Note: R9/R10 text that "`calibrate-rim` is not primary mixture input" means the
**value-rim** adapter must not take calibrate-rim as its primary input. R12 is a
**parallel** research ingest path, not a change to R9 semantics.
