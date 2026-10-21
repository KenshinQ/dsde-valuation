# SYNTHETIC mature operating company (VMS-0.2 Phase 0)

**SYNTHETIC DATA: no real company, no investment meaning.**

This example is the VMS-0.2 Phase 0 offline baseline (SPEC §19 / §20 Phase 0).
It reuses the same seeded generator as `examples/synthetic_operating_company/`
(instrument `SYN000001.SZ`) and emits a **contracts-only** result bundle:

- validates default config + empty method registry + router + profiles catalog
- writes `request.json`, `config_snapshot.json`, `data_manifest.json`,
  `method_eligibility.json` (all `NOT_RUN`), `validation_report.json`,
  `simulation_metadata.json` with `schema_version=vms-0.2.phase2` and
  `INVESTMENT_VALUE_NOT_ESTABLISHED`
- does **not** classify profiles, route methods, or run DCF/returns

```bash
# from repo root, after editable install
vms phase0 --out /tmp/vms_phase0 --seed 42
# or:
python examples/synthetic_mature_operating/run_phase0.py --out /tmp/vms_phase0 --seed 42
```

Expected qualitative behavior (Phase 0):

- config / registry / request validation PASS
- `enabled_methods == 0`
- every catalog method id appears as `NOT_RUN`
- same seed ⇒ identical deterministic artifact hashes (exact bytes)

Routing / method eligibility assertions arrive in Phase 2+; this example must
not assert fictitious investment performance.
