# VMS-0.1.0 Release Notes

**Not an alpha / investability claim.** Synthetic engineering release only.
`investment_value` defaults to `INVESTMENT_VALUE_NOT_ESTABLISHED`.

## What’s in 0.1.0

- End-to-end valuation & conditional-return pipeline for the `operating_company` profile.
- Optional DSDE adapter (`vms.adapters.dsde`) — core runs with DSDE absent.
- Versioned output contract `schema_version: vms-0.1.0`.
- Model card, architecture, data contracts, offline e2e demo script.
- Chronological walk-forward evaluation; random splits prohibited.
- Sensitivity / uncertainty attribution (MC percentiles ≠ CIs).

## What is deliberately not claimed

- No portfolio alpha, Kelly sizing, or live trading recommendations.
- No `INVESTMENT_VALUE_SUPPORTED` on SYNTHETIC data.
- No HiThink / Wind live A-share adapter (future work).
- No calibration pass on real-market OOS.

## Upgrade / schema

Prior phase stamps (`vms-0.1.phaseN`) are superseded by `vms-0.1.0` for this packaging.
Consumers should key off `schema_version` and `schema_kind`.

## Offline demo

```bash
uv venv .venv --python 3.11
uv pip sync --python .venv/bin/python requirements.lock
uv pip install --python .venv/bin/python --no-deps -e .
scripts/e2e_offline_demo.sh /tmp/vms_e2e
.venv/bin/python -m pytest -q
```

## Definition of Done

See `PHASE10_DONE.md` § Definition of Done — all items evidenced; **no alpha claim**.
