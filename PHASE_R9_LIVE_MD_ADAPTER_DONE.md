# Phase R9 — Live MethodDistribution adapter: DONE

Date: 2026-10-25 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/r9-live-md-adapter`. Prior: [PHASE_R8_PRIOR_ONLY_FI_DONE.md](PHASE_R8_PRIOR_ONLY_FI_DONE.md).

Status: **R9 live value-rim → MethodDistribution adapter accepted** for research
PRIOR_ONLY path only. Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. **Not** investment
advice. **No** `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.
Does **not** claim calibrated production ensemble. SCHEMA stays `vms-0.2.phase12`;
package `0.2.0rc1`. Architecture gate B1 fix: Track B never feeds raw
`pb_center_used` (P/B multiple) as PER_SHARE; maps `exit_prices.summaries[*].p50`
or SKIP `TRACK_B_CENTER_NOT_PER_SHARE`.

## Scope
Wire single-ticket `vms value-rim` out-dir artifacts into
`list[MethodDistribution]` for existing `build_prior_only_fi_bundle(components=...)`.
Reuses R8 sanitize / allow-list / production refusal. Does not replace synthetic
`vms phase8` or R8 demo scenarios when `--from-value-rim` is omitted.

## Changed / added files
```
src/vms/reporting/fi_method_distribution_adapter.py   NEW: live adapter
src/vms/reporting/prior_only_fi_bundle.py             data_label / source_meta / live cite
src/vms/cli/main.py                                   --from-value-rim DIR
src/vms/assumptions.py                                ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1
docs/assumptions.md                                   regenerated
docs/calibration_protocol.md                          R9 section
tests/unit/test_r9_live_md_adapter.py                 NEW: AC1–AC5
tests/integration/test_cli_prior_only_fi_r9.py        NEW: CLI live + demo regression
PHASE_R9_LIVE_MD_ADAPTER_DONE.md                      this file
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | Fixture value-rim → research PRIOR_ONLY mixture; calibrated_claim=false; allow-list | `test_ac1_*` |
| 2 | Same components production intent → mixture null | `test_ac2_*` |
| 3 | Track B hist_n&lt;12 → SKIP, not in weights | `test_ac3_*` |
| 4 | Without `--from-value-rim`, R8 synthetic demo unchanged | `test_ac4_*`; CLI demo test |
| 5 | SCHEMA/package unchanged; forbidden labels locked | `test_ac5_*` |

## Centers (pinned)
- Track A: `method_result.values.value_per_share` preferred; else `rim_distribution.ke_grid[0].vps_p50`
- pb_common optional: `rim_pb_roe.relative_vps` when ok
- Track B PER_SHARE: prefer `rim_track_b.exit_prices.summaries[<h>].p50`
  (exit_price_per_share median; first finite horizon) or explicit `exit_vps_center`.
  `pb_center_used` is own-hist **P/B multiple** (audit only) — never PER_SHARE weights.
  Both `hist_n >= MIN` **and** mapped PER_SHARE center required; else SKIP
  (`HIST_PB_BELOW_MIN` / `TRACK_B_CENTER_NOT_PER_SHARE`).
- Samples: `samples_from_point(center)`; `diagnostics.synthetic=false` +
  `sample_generation=samples_from_point` + source paths

## Hard constraints honored
- Never emit `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`
- Production `intent=production` refuses mixture
- Track B &lt; MIN=12 → SKIP, not in weights (no invent OEI / no default PB)
- No lift of `industry.unsupported` / non-bank FI
- calibrate-rim not primary input; R7 prefer_local / calibrate-rim guards untouched
- No scattered sector tokens outside `assumptions.py`
- Without `--from-value-rim`, R8 demo path unchanged

## Known gaps (honest)
- Minimal slice still uses `samples_from_point` around centers (not full live sample paths);
  stamped as `sample_generation=samples_from_point` with `synthetic=false`.
- Track B requires a mapped PER_SHARE exit center (`exit_prices.summaries[*].p50`);
  raw `pb_center_used` P/B multiple is audit-only and never enters PER_SHARE weights
  (`EVAL-IV-NOT-PRICE-TRUTH-v1` still applies to the exit channel).
- Production calibrated ensemble still blocked (`CALIBRATION_INSUFFICIENT` remains honest).

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — live PRIOR_ONLY ingest ≠ investment advice.
