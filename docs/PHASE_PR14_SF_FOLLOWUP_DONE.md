# Phase PR14 SF1–SF3 follow-up: DONE

Date: 2026-10-27 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `feat/pr14-sf1-sf3-followup`. Base: master @ `4c43fe8` (R13 merged).
SPEC: `/workspace/PR14_SF1_SF3_SPEC.md`. Pace: **pr14-sf**.

Status: **SF1–SF3 CLOSED** (local branch + PR; merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items

| ID | Change | Status |
|----|--------|--------|
| SF1 | `SOURCE_ID` → `fi_peer_universe_v2` (observation stamp); assumption cite remains `RIM-FI-PEER-UNIVERSE-v2` | CLOSED |
| SF2 | `list_deposit_taking_fi_thscodes` Exception → `[]` + warning once (`exc_info=True`); missing duckdb/file/empty label stay silent | CLOSED |
| SF3 | Unit `discover_bank_candidates` / `build_fi_peer_observations` calls pin explicit `fund_db` (missing/tmp or real panel path) | CLOSED |

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`
- package `0.2.0rc1`
- `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- No invent OEI / default PB; no 非银 lift; no curated default flip
- No calibrate-rim / rim_run / value-rim emitter rewrites
- Peer discovery semantics unchanged (classifications-only default from R13)

## Touch list

- `src/vms/methods/rim/bank_peers.py` (SF1)
- `src/vms/providers/eastmoney/store.py` (SF2)
- `tests/unit/methods/test_rim_r3_bank_peers.py` (SF3 + SF1 assert + SF2 test)
- `tests/unit/methods/test_rim_r4_fi_peer_panel.py` (SF3 AC3 pin; discover path had none)
