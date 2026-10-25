# R5 — Subject own-hist P/B depth (TE+OEI+shares+raw_close): DONE

Date: 2026-10-25 (Asia/Shanghai). Branch: `feat/r5-subject-hist-depth` (from `58160eb` / R4 merge).
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
Prior: `PHASE_R4_FI_PEER_PANEL_DONE.md`. Pace: **r5-default** (user widget).

Status: **R5 acceptance criteria pass** (depth builder + value-rim wire + year funnel + unit/smoke).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim OOS calibration, ensemble, gate lift, 非银金融 support, schema bump, or `pit_complete=true`.
Does **not** lower `MIN_HIST_PB_POINTS` (=12) or invent OEI / default pb=2.0.

## Design
- **Root cause addressed**: Track B UNAVAILABLE was often unload-thin subject series (OEI/TE/shares/px), not the R2d formula (synthetic n≥12 already VALID). R5 deepens the **subject** LoadResult plane before PIT assess.
- **Builder** (`methods/rim/subject_hist_depth.py` → `build_subject_hist_depth` + `merge_subject_hist_into_load`):
  - TE from HiThink annual balance (NOTICE-aligned)
  - OEI/MI/… from EM `bank_f10` (subject `max_annual` default **20**)
  - `raw_close` + shares (price lookback default **20y**)
  - path diagnostics (`te_path` / `bank_f10_path` / `equity_path` / `prices_path` / `rest_calls`)
- **Local-first**: `prefer_local=True` (default / no CLI `--refresh`) ⇒ **zero REST even on miss**.
- **`--refresh`**: allow Recipe E / EM upsert; fail → local fallback or empty; never invent OEI.
- **Year funnel**: `historical_common_pb` emits structured `year_funnel` (`INCLUDED` | `SKIP_*` + reason); surfaced in `rim_track_b.json` / summary.
- **value-rim**: deepen subject before `assess` (default ON). Flags: `AUTO_SUBJECT_HIST_DEPTH` + depth flags. Artifact `rim_subject_hist.json`.
- **Assumption**: `RIM-SUBJECT-HIST-DEPTH-v1`.
- Legacy `industry.unsupported` / `vms value|project` gate **untouched**. SCHEMA remains `vms-0.2.phase12`.

## Changed / added files
```
src/vms/methods/rim/subject_hist_depth.py       NEW subject hist depth builder
src/vms/methods/rim/hist_pb.py                  year_funnel entries
src/vms/methods/rim/track_b_exit.py             hist_pb.year_funnel in payload
src/vms/methods/rim/bank_peer_panel.py          bank_f10 max_annual param (R4 default 12)
src/vms/reporting/value_rim_bundle.py           deepen before assess + artifact/summary
src/vms/cli/main.py                             --refresh help covers R5
src/vms/assumptions.py / docs/assumptions.md    RIM-SUBJECT-HIST-DEPTH-v1
tests/unit/methods/test_rim_r5_subject_hist_depth.py
PHASE_R5_SUBJECT_HIST_DEPTH_DONE.md
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | Subject hist depth merges TE+OEI+shares+raw_close + path diag | `subject_hist_depth.py`; unit merge/path tests |
| 2 | No `--refresh` → zero REST when local present | `test_prefer_local_zero_rest_when_local_present` |
| 3 | `--refresh`: upsert allowed; fail→local/empty; no invent OEI | `test_refresh_fail_falls_back_or_empty` |
| 4 | Year-level skip funnel (MISSING_OEI etc.) | `test_year_funnel_marks_missing_oei_and_included`; track_b payload |
| 5 | MIN_HIST_PB_POINTS stays 12; no default pb=2.0 | `test_min_hist_pb_points_unchanged`; Track B VALID uses hist median |
| 6 | Synthetic deep series → Track B VALID (n≥12) | `test_track_b_valid_when_hist_ge_12_after_deep_series`; wiring test |
| 7 | value-rim wires deepen before assess; artifact | `test_wiring_*`; `rim_subject_hist.json` |
| 8 | 000001 smoke: n≥12 **or** honest year funnel (not unload false-positive) | smoke notes below |
| 9 | legacy unsupported unchanged | design / prior R4 gate |
| 10 | INVESTMENT_VALUE_NOT_ESTABLISHED | summary + artifacts |
| 11 | `pit_complete=false` | smoke summary |
| 12 | pytest green + PHASE_R5 + assumption | this file; `RIM-SUBJECT-HIST-DEPTH-v1` |

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `python -m pytest` | **753 passed** |
| Smoke local | `vms value-rim ... --out /tmp/vms_000001_rim_r5_local` (no `--refresh`) | subject rest=0; merged +37 fin; Track B UNAVAILABLE n=9; year_funnel INCLUDED×9 + SKIP_NO_COMMON_EQUITY×2 (MISSING_OEI@2014/2015) |
| Smoke refresh | `vms value-rim ... --refresh --out /tmp/vms_000001_rim_r5_refresh` | subject rest=2 (bank_f10+equity upsert); still n=9 UNAVAILABLE (vendor OEI from 2016); honest funnel |

## Smoke notes (000001.SZ @ 2025-06-30, Asia/Shanghai)
Vendor OEI for 000001 begins ~2016; local marketdb raw_close also from 2016-09. Even with F10 `max_annual=20` + `--refresh`, economic OEI history under PIT is **9** FY (2016–2024) → Track B **UNAVAILABLE** with honest `year_funnel` (`SKIP_NO_COMMON_EQUITY` / `MISSING_OTHER_EQUITY_INSTRUMENTS` for 2014–2015). That is design-honest, not a formula failure. Synthetic unit path proves n≥12 → VALID without inventing OEI or lowering the floor. Artifacts: `rim_subject_hist.json`, `rim_track_b.json` (year_funnel).

## Known gaps (honest)
- SCHEMA_VERSION remains `vms-0.2.phase12` (no bump per R5 scope).
- Walk-forward calibration / ensemble / gate lift / 非银金融 out of scope.
- Recipe E price deepen may need lab `dotenv` on some boxes; local-first path remains REST-free.
- Banks whose OEI line is shorter than 12 FY cannot open Track B without inventing OEI (forbidden) or lowering MIN (forbidden).

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — engineering smoke ≠ investment advice.
