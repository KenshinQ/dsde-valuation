# Phase pr24-sf-hygiene: DONE

Date: 2026-10-29 (Asia/Shanghai). Repo: KenshinQ/dsde-valuation.
Branch: `chore/pr24-sf-hygiene`. Base: master @ `7fac001` (PR#24 merged).
SPEC: `/workspace/PR24_SF_HYGIENE_SPEC.md`. Pace: **pr24-sf-hygiene**.
Source: `/workspace/agent-tools/pr24-review/VERDICT.md` SHOULD-FIX SF1–SF2.

Status: **AC CLOSED** (local branch + PR; merge authority kenshin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
Never claims `ENSEMBLE_CALIBRATED` / `CALIBRATION_PASS` / `INVESTMENT_VALUE_SUPPORTED`.

## Closed items

| AC | Criterion | Status |
|----|-----------|--------|
| 1 | SF1: FCFF plugin-level equity_value identity pin (with/without midcycle series) | CLOSED |
| 2 | SF2: production MR→MD builder preserves midcycle_estimate; phase8 wired | CLOSED |
| 3 | Existing midcycle / emitter / Phase5 / Phase12 tests green | CLOSED (local) |
| 4 | SCHEMA `vms-0.2.phase12` / package `0.2.0rc1` / MIN=12 / IV unchanged | CLOSED |
| 5 | PR against master; merge authority kenshin | CLOSED (PR opened; not merged) |

## Change summary

- **SF1**: `test_sf1_fcff_plugin_equity_value_identity_with_without_midcycle_series` — real `fcff_dcf` plugin + minimal FinancialPathBundle; cyclical with vs without PIT series → `equity_value` / `enterprise_value` / `value_per_share` identical; midcycle only under diagnostics (HIGH vs LOW).
- **SF2**: `method_distribution_from_result` production builder in `ensemble/mixture.py` (uses `diagnostics_with_midcycle_passthrough`); phase8 `_components_from_method_results` wires it on the MR→MD path; tests pin helper + phase8 round-trip; no invent when source lacks midcycle. FI adapters untouched (still must not invent).
- **Behavior**: Y/N = **N** for λ / HIGH / Phase5 inject / CF-RIM valuation math. Diagnostics provenance + tests + DONE only.

## Unchanged (hard constraints)

- SCHEMA `vms-0.2.phase12`
- package `0.2.0rc1`
- `MIN_HIST_PB_POINTS=12`
- `INVESTMENT_VALUE_NOT_ESTABLISHED`
- λ / HIGH gate / Phase5 `HIGH ∧ denom>0` inject
- No midcycle denom inside DCF/RIM valuation
- No slice D; no invent OEI; no 非银 lift; no ENSEMBLE_CALIBRATED flip

## Touch list

- `src/vms/ensemble/mixture.py` (`method_distribution_from_result`)
- `src/vms/ensemble/__init__.py` (export)
- `src/vms/reporting/phase8_bundle.py` (production MR→MD wire)
- `tests/unit/test_midcycle_emitter_wiring.py` (SF1 + SF2)
- `PHASE_PR24_SF_HYGIENE_DONE.md`

## Local verification

```text
.venv/bin/python -m pytest \
  tests/unit/test_midcycle_skel.py \
  tests/unit/test_phase5_acceptance.py \
  tests/unit/test_midcycle_emitter_wiring.py \
  tests/unit/test_phase8_acceptance.py \
  tests/unit/test_docs_sync.py \
  tests/unit/test_phase12_acceptance.py \
  tests/unit/test_profiles.py -q
```
