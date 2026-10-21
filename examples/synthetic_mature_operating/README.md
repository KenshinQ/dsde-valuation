# synthetic_mature_operating (VMS-0.2 Phase 12)

**SYNTHETIC DATA: no real company, no investment meaning.**
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.

Pattern: `mature_operating` — Full Track A cash-flow methods + Track B exit/returns

## Run

```bash
vms phase12 --out /tmp/vms_mature_operating --pattern mature_operating --seed 42 --paths 20 --years 3
# or:
python examples/synthetic_mature_operating/run_e2e.py --out /tmp/vms_mature_operating --seed 42
```

Asserts routing / validity diagnostics only — **not** fictitious investment performance.

See also `examples/profile_fixtures/` and `docs/model_card.md`.

## Phase 12 — end-to-end release example

```bash
vms phase12 --out /tmp/vms_mature --pattern mature_operating --seed 42 --paths 20
python examples/synthetic_mature_operating/run_e2e.py --out /tmp/vms_mature
```

Emits method results, router decisions, market exit prices, return distributions and
diagnostics. Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.
