# Phase R13 — FI peer classifications-only default: DONE

Date: 2026-10-27 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/r13-fi-peer-classifications-only`. Prior: [PHASE_R2E_FI_PEER_UNIVERSE_DONE.md](PHASE_R2E_FI_PEER_UNIVERSE_DONE.md),
[PHASE_R4_FI_PEER_PANEL_DONE.md](PHASE_R4_FI_PEER_PANEL_DONE.md).
SPEC: `/workspace/FI_PEER_CLASSIFICATIONS_ONLY_SPEC.md`. Pace: **r13-default**.

Status: **R13 acceptance criteria implemented** (local branch + PR; merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Goal
Candidate discovery SoT = **PIT SW L1 classifications plane only**
(`InstrumentClassification` ∪ local fund DuckDB `em_industry_profile` where
`sw_l1_proxy == deposit_taking_fi_sw_label()`).

Default path **stops** unioning `LEAN_CURATED_DEPOSIT_TAKING_FI`, closing the
R2E lean-v1 dual-universe default gap.

## Design
1. `discover_bank_candidates` / `build_fi_peer_observations` / `build_fi_peer_panel`
   → `use_lean_curated: bool = False`.
2. New local-first helper `list_deposit_taking_fi_thscodes` in
   `providers/eastmoney/store.py` (missing DB/table/duckdb → `[]`; zero REST).
3. Default membership: `store_ids ∪ PIT classifications matching YAML bank label
   ∪ extras − subject`. Curated only when `use_lean_curated=True`.
4. Flags: `CLASSIFICATIONS_ONLY_CANDIDATES` (default);
   `LEAN_CURATED_CANDIDATES` only on opt-in.
5. Assumption `RIM-FI-PEER-UNIVERSE-v2` (supersedes v1). Cite from panel/builder.
6. Keep curated tuple / `lean_curated_peer_ids` / `lean_curated_ids()` /
   calibrate-rim `lean_curated_size` / `config/universe.fi_deposit_lean.yaml`.

## Hard constraints (PASS)
- SCHEMA `vms-0.2.phase12`; package `0.2.0rc1`; `MIN_HIST_PB_POINTS=12`.
- No invent OEI / default PB; no 非银 / industry.unsupported lift;
  `subject_allows_auto_fi_peers` unchanged.
- No rewrite of calibrate-rim / rim_run / rim_forecast beyond peer discovery default.
- Always `INVESTMENT_VALUE_NOT_ESTABLISHED`.

## Honest notes
- Thin local `em_industry_profile` (subject-only) → honest `PEER_SCARCITY` until
  ingest enriches more names — **by design**, not a silent curated fill.
- Synthetic bank panel / calibrate-rim lean universe IDs stay as separate data planes.

## R2E known gap → CLOSED (dual-universe default)
R2E ownership note 「Dual-universe drift accepted for lean v1; prefer
classifications-only once panel is rich.」 — **default path CLOSED by R13**.
Curated remains available as explicit opt-in.

## Changed files
```
src/vms/providers/eastmoney/store.py          list_deposit_taking_fi_thscodes
src/vms/methods/rim/bank_peers.py             default False + store seed + v2 cite/flags
src/vms/methods/rim/bank_peer_panel.py        default False + fund_db → discover + flags
src/vms/assumptions.py / docs/assumptions.md  RIM-FI-PEER-UNIVERSE-v2 + SUPERSEDED
tests/unit/methods/test_rim_r3_bank_peers.py  AC1–AC3/AC5/AC6/AC8 + v2 assert
tests/unit/methods/test_rim_r4_fi_peer_panel.py  panel flags + lean TE-load pin
PHASE_R13_FI_PEER_CLASSIFICATIONS_ONLY_DONE.md
PHASE_R2E_FI_PEER_UNIVERSE_DONE.md            gap CLOSED pointer
```

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — engineering change ≠ investment advice.
