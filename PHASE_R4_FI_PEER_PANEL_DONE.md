# R4 — Deposit-taking FI multi-instrument peer panel: DONE

Date: 2026-10-25 (Asia/Shanghai). Branch: `feat/r4-fi-peer-panel` (from `fa1eeed` / R3 merge).
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
Prior: `PHASE_R2E_FI_PEER_UNIVERSE_DONE.md`. Pace: **r4-default** (user widget).

Status: **R4 acceptance criteria pass** (panel builder + value-rim wire + unit/smoke).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim OOS calibration, ensemble, gate lift, 非银金融 support, schema bump, or `pit_complete=true`.

## Design
- **Root cause addressed**: R3 peer build was subject-only — peer TE/OEI/shares were never loaded, so funnel was unload-driven `MISSING_FINANCIALS×N`. R4 adds a multi-instrument panel so R3 sees real peer rows.
- **Builder** (`methods/rim/bank_peer_panel.py` → `build_fi_peer_panel`): for each lean-curated / SW deposit-taking candidate (ex-subject), merge:
  - TE from HiThink annual balance (NOTICE-aligned published_at)
  - OEI/MI from EM `bank_f10` companyType=3
  - `raw_close` from marketdb + shares from EM equity
  - optional SW L1 classification
  - **per-ticker path diagnostics** (`te_path` / `bank_f10_path` / `equity_path` / `prices_path` / `rest_calls`)
- **Local-first**: `prefer_local=True` (default / no CLI `--refresh`) ⇒ **zero REST even on miss**; missing surfaces as path diag + later peer exclusion. Never invent OEI.
- **`--refresh`**: allow Recipe E / EM upsert; fail → local fallback or exclude.
- **value-rim**: when auto FI peers ON and subject is deposit-taking SW, build panel then `build_fi_peer_observations(load ⊕ panel)`. Flags: `AUTO_FI_PEER_PANEL` + panel universe flags. Artifact `rim_fi_peers.json` includes `panel`.
- **Assumption**: `RIM-FI-PEER-PANEL-v1`.
- Legacy `industry.unsupported` / `vms value|project` gate **untouched**. SCHEMA remains `vms-0.2.phase12`.

## Changed / added files
```
src/vms/methods/rim/bank_peer_panel.py          NEW panel builder
src/vms/reporting/value_rim_bundle.py           auto-wire panel before R3
src/vms/cli/main.py                             value-rim --refresh → prefer_local_fi_peers=False
src/vms/assumptions.py / docs/assumptions.md    RIM-FI-PEER-PANEL-v1
tests/unit/methods/test_rim_r4_fi_peer_panel.py
tests/unit/methods/test_rim_r3_auto_fi_wiring.py  stub panel (keep R3 unit-fast)
PHASE_R4_FI_PEER_PANEL_DONE.md
```

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `python -m pytest` | **742 passed** |
| Smoke local | `vms value-rim ... --out /tmp/vms_000001_rim_r4_local` (no `--refresh`) | panel rest=0; funnel `MISSING_OTHER_EQUITY_INSTRUMENTS×19` (not unload `MISSING_FINANCIALS`); R2c PEER_SCARCITY |
| Smoke refresh | `vms value-rim ... --refresh --out /tmp/vms_000001_rim_r4_refresh` | panel rest>0; **n_peers=19 INCLUDED**; R2c **VALID** |
| Legacy | `vms project` on bank industry | still **UNSUPPORTED_PROFILE** |

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | `build_fi_peer_panel` merges multi-instrument + per-ticker path diag | `bank_peer_panel.py`; `test_panel_merges_multi_instrument_with_path_diag` |
| 2 | No `--refresh` → zero REST when local present | `test_panel_prefer_local_zero_rest_when_local_present`; local smoke `panel.rest_calls=0` |
| 3 | `--refresh`: upsert allowed; fail→local/exclude; no invent | `test_panel_refresh_fail_falls_back_or_excludes`; refresh smoke upsert paths |
| 4 | TE without OEI → `MISSING_OTHER_EQUITY_INSTRUMENTS` | `test_panel_te_without_oei_excludes_missing_other_equity`; local smoke funnel |
| 5 | PIT leakage tests | `test_panel_pit_leakage_future_rows_excluded` |
| 6 | value-rim auto uses multi-ticket panel not subject-only | `test_wiring_uses_panel_not_subject_only`; `AUTO_FI_PEER_PANEL` |
| 7 | 000001 smoke: n≥peer_min **or** honest funnel (not all MISSING_FINANCIALS unload) | local: OEI miss×19; refresh: n=19 VALID |
| 8 | legacy unsupported unchanged | `vms project` → UNSUPPORTED_PROFILE |
| 9 | INVESTMENT_VALUE_NOT_ESTABLISHED | summary + artifacts |
| 10 | `pit_complete=false` | smoke summary |
| 11 | pytest green + PHASE_R4 + assumption | this file; `RIM-FI-PEER-PANEL-v1` |

## Smoke notes (000001.SZ @ 2025-06-30, Asia/Shanghai)
- **Local-first**: TE+prices for 19 lean peers from DuckDB; bank_f10/equity miss → honest `MISSING_OTHER_EQUITY_INSTRUMENTS` (R3 AC preserved; unload false-positive fixed).
- **Refresh**: EM F10+equity upsert for lean peers → 19 `INCLUDED`; R2c VALID with peer median P/B. Still `INVESTMENT_VALUE_NOT_ESTABLISHED`; R2d hist n&lt;12 → UNAVAILABLE; no calibration claim.

## Known gaps (honest)
- SCHEMA_VERSION remains `vms-0.2.phase12` (no bump per R4 scope).
- Walk-forward calibration / ensemble / gate lift / 非银金融 / Track B hist length out of scope.
- Dual-universe lean curated vs live SW drift unchanged (R3 note).

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — engineering smoke ≠ investment advice.
