# synthetic_holding_company (VMS-0.2 Phase 12)

**SYNTHETIC DATA: no real company, no investment meaning.**
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.

Pattern: `holding` — SOTP/NAV with schedules + data-gap demo

## Run

```bash
vms phase12 --out /tmp/vms_holding --pattern holding --seed 42 --paths 20 --years 3
# or:
python examples/synthetic_holding_company/run_e2e.py --out /tmp/vms_holding --seed 42
```

Asserts routing / validity diagnostics only — **not** fictitious investment performance.

See also `examples/profile_fixtures/` and `docs/model_card.md`.
