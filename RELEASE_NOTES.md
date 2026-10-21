# VMS-0.2.0rc1 Release Notes

**Not an alpha / investability claim.** Synthetic engineering release only.
`investment_value` remains `INVESTMENT_VALUE_NOT_ESTABLISHED`.
`INVESTMENT_VALUE_SUPPORTED` is **not** emitted. `ENSEMBLE_CALIBRATED` is **not** claimed.
Calibration status: `CALIBRATION_INSUFFICIENT` (honest pre-release).

Schema: `vms-0.2.phase12`. Package: `0.2.0rc1`. Tag (local): `vms-0.2-phase12`.

## What’s in 0.2.0rc1 (Phase 12)

- Adaptive Multi-Method engine through Phases 0–11 (profile → router → methods →
  market exit → returns → walk-forward / sensitivity).
- Phase 12 packaging: model card, architecture, data contracts, method registry,
  calibration protocol docs.
- Five offline synthetic examples: mature operating, growth/neg-FCF, bank, cyclical,
  holding (`vms phase12`, `scripts/run_offline_examples.sh`).
- Result-bundle validation (`vms validate-bundle`) against SPEC §16.3 subsets.
- Schema / configuration version migration tests (phase0…phase12 stamps).
- Optional DSDE adapter retained (`vms.adapters.dsde`); core does not require DSDE.

## Migration from phase stamps

Prior schema stamps `vms-0.2.phase0` … `vms-0.2.phase11` are superseded by
`vms-0.2.phase12` for this packaging. Config sidecars bump to `*.phase12`.
Consumers should key off `schema_version` and `implemented_phase`.

Archived VMS-0.1: `SPEC_VMS-0.1.md`, tag `vms-0.1`.

## What is deliberately not claimed

- No portfolio alpha, Kelly sizing, or live trading recommendations.
- No `INVESTMENT_VALUE_SUPPORTED` on SYNTHETIC data or unit tests.
- No production `ENSEMBLE_CALIBRATED` weights.
- No real A-share long-history OOS calibration pass.
- Real-data PIT completeness remains an honest gap (`pit_complete` may be false).

## Offline demo

```bash
uv venv .venv --python 3.11
uv pip sync --python .venv/bin/python requirements.lock
uv pip install --python .venv/bin/python --no-deps -e .
scripts/run_offline_examples.sh /tmp/vms_offline
.venv/bin/python -m pytest -q
```

## Definition of Done

See `PHASE12_DONE.md` — Phase 12 acceptance + SPEC §23 mapped with explicit deferrals.
