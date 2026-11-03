# MATURE lean walk-forward calibrate harness: DONE

Date: 2026-11-03 (Asia/Shanghai). Branch: `feat/mature-lean-wf-calibrate` (from `b503b32`).
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
Prior: Phase 11 evaluate / R6–R7 calibrate-rim pattern (methods **not** copied from RIM).
SPEC: `/workspace/NONFI_MATURE_LEAN_WF_SPEC.md` (slice B).

Status: **acceptance criteria pass** (synthetic lean CLI + mature_real DATA_GAP scaffold).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim `CALIBRATION_PASS`, `ENSEMBLE_CALIBRATED`, `INVESTMENT_VALUE_SUPPORTED`,
GROWTH/CYCLICAL/HOLDING parallel, PRIOR_ONLY non-FI, midcycle inject, invent OEI,
lower `MIN_HIST_PB_POINTS`, or SCHEMA/package bump.

## Design
- **Reuse Phase 11 evaluate**: chronological-only, freeze-before-test,
  forecast-before-outcome, separate operating/CF/multiples targets,
  `pit_complete=false` → exclude from `scores_unbiased`,
  hard `CALIBRATION_INSUFFICIENT` + `INVESTMENT_VALUE_NOT_ESTABLISHED`.
- **Not RIM**: no Track B hist_pb / OEI path; FI calibrate-rim untouched.
- **Universes**:
  - `config/universe.mature_lean.yaml` (`mature_synthetic`, `data_label: SYNTHETIC`)
  - `config/universe.mature_lean_real.yaml` (`mature_real` scaffold; no invent)
- **CLI**: `vms calibrate-mature` (default lean synthetic; optional `--refresh`)
- **Assumptions**: `EVAL-MATURE-LEAN-WF-v1` / `EVAL-MATURE-LEAN-REAL-OOS-v1`
- SCHEMA remains `vms-0.2.phase12`; package `0.2.0rc1`.

## Changed / added files
```
config/universe.mature_lean.yaml                 NEW synthetic lean
config/universe.mature_lean_real.yaml            NEW real scaffold
src/vms/evaluation/universe.py                  mature_synthetic / mature_real kinds
src/vms/evaluation/run.py                       prefer_local forwarded
src/vms/reporting/calibrate_mature_bundle.py    NEW bundle + hard gates
src/vms/cli/main.py                             calibrate-mature command
src/vms/assumptions.py / docs/assumptions.md    EVAL-MATURE-LEAN-*-v1
docs/calibration_protocol.md                    MATURE section
tests/integration/test_cli_calibrate_mature.py  CLI smoke + real gap + FI refuse
tests/unit/test_mature_lean_wiring.py           materialize wiring
PHASE_MATURE_LEAN_WF_DONE.md
```

## Acceptance → evidence

| # | Criterion | Evidence |
|---|---|---|
| 1 | mature lean YAML (+ optional real scaffold) | config YAMLs; load tests |
| 2 | materialize kinds + mutual exclusion | `test_mature_lean_wiring.py` |
| 3 | CLI `vms calibrate-mature` | help + CLI smoke |
| 4 | assumption ids + chrono / forecast-before-outcome | summary `assumption`; Phase11 reuse |
| 5 | hard INSUFFICIENT + IV_NOT_ESTABLISHED; no silent PASS | CLI asserts + bundle guards |
| 6 | synthetic smoke green; real data-gap honest | integration tests |
| 7 | DONE + calibration_protocol section | this file; docs section |
| 8 | no SCHEMA/package bump; thin PR | pyproject unchanged |

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `pytest tests/unit/test_mature_lean_wiring.py tests/integration/test_cli_calibrate_mature.py` | expected green |
| CLI | `vms calibrate-mature --out /tmp/vms_mature --universe config/universe.mature_lean.yaml` | `CALIBRATION_INSUFFICIENT`; `not_rim=true` |

## Non-goals (honored)
- No GROWTH / CYCLICAL / HOLDING
- No non-FI PRIOR_ONLY
- No midcycle inject into DCF/RIM/ensemble
- No live trading
- No CALIBRATION_PASS plumbing (slice C)

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — mature lean walk-forward harness ≠ investment advice.
