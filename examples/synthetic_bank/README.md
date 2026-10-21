# synthetic_bank (VMS-0.2 Phase 12)

**SYNTHETIC DATA: no real company, no investment meaning.**
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.

Pattern: `financial_institution` — RIM path; industrial FCFF disabled.

## Run

```bash
vms phase12 --out /tmp/vms_financial_institution --pattern financial_institution --seed 42 --paths 20 --years 3
python examples/synthetic_bank/run_e2e.py --out /tmp/vms_financial_institution --seed 42
```

Asserts routing / validity diagnostics only — **not** fictitious investment performance.
