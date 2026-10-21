# Phase 0 — completion report (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2); archive: `SPEC_VMS-0.1.md`.

Status: **all Phase 0 acceptance criteria pass** for contracts/baseline.
Label: `ENGINEERING_PASS` for Phase 0 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** a valuation and does **not** claim investment value.

## Changed / added files (VMS-0.2 Phase 0)
```
src/vms/__init__.py                          # SCHEMA_VERSION=vms-0.2.phase0, PHASE_0, 0.2.0a0
src/vms/schemas/contracts.py                 # NEW: targets, profiles, method/claim statuses, registry models
src/vms/schemas/__init__.py                  # export 0.2 contracts
src/vms/schemas/observations.py              # ValuationRequest.target (ValuationTarget)
src/vms/schemas/config.py                    # load method_registry / router / profiles sidecars
src/vms/reporting/phase0_bundle.py           # NEW: Phase 0 offline bundle emitter
src/vms/cli/main.py                          # `vms phase0` command
config/default.yaml                          # vms-default-0.2.phase0 + sidecar paths
config/method_registry.yaml                  # NEW: empty registry (validated)
config/router.yaml                           # NEW: placeholder router policy
config/profiles.yaml                         # NEW: §7.2/§10.3 catalog (not a classifier)
examples/synthetic_mature_operating/         # NEW: README + run_phase0.py
tests/unit/test_contracts_v02.py             # NEW
tests/integration/test_cli_phase0.py         # NEW
tests/unit/test_config.py                    # sidecar copy + fake-enabled rejection
tests/unit/test_package_skeleton.py          # Phase 0 version + anti-stub check
tests/*/…                                    # schema_version assertions → vms-0.2.phase0
docs/assumptions.md                          # regenerated (EM-BS-LINES-v1 sync)
pyproject.toml / PHASE0_DONE.md / README.md / CI / e2e schema prefix
```

Legacy VMS-0.1 modules under `src/vms/{pit,valuation,…}` remain importable for continuity;
they are **not** claimed as completed VMS-0.2 Phases 1–12. Empty `vms.methods` /
`vms.router` / `vms.profiles` packages were **not** created (SPEC §22/§24 anti-stub).

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `uv pip install --no-deps -e .` then `python -m pytest` | **509 passed** |
| Offline demo | `vms phase0 --out /tmp/vms_phase0 --seed 42` | exit 0; bundle with schema provenance |

## Acceptance criterion → evidence

| # | Criterion (SPEC §20 Phase 0) | Evidence |
|---|---|---|
| 1 | Clean env installs and runs tests + one offline demo | Editable install via `uv pip install --no-deps -e .`; `pytest` green; `vms phase0 --out … --seed 42` writes bundle. Example: `examples/synthetic_mature_operating/run_phase0.py`. |
| 2 | Invalid types, timestamps, units, enums, config bounds fail actionably | Existing `tests/unit/test_schemas.py` (naive tz, units, currencies, quality_status); `tests/unit/test_config.py` (bounds + file path in message); **new** `tests/unit/test_contracts_v02.py` (bad ValuationTarget, bad router target, bad profile label, enabled+NOT_IMPLEMENTED rejected); `tests/integration/test_cli_phase0.py::test_phase0_invalid_target_exit_2`, `test_phase0_naive_as_of_exit_2`. |
| 3 | Same input/data/config/seed reproduces within tolerance | `test_phase0_same_seed_reproduces`: sha256 of all Phase 0 deterministic artifacts + data CSVs identical for seed=7; different seed changes data + run_id. Tolerance documented in `simulation_metadata.json` as exact bytes on same lock/code. |
| 4 | No imports from prior PIT/FTD/DV1/Thorp-engine/legacy projects | `tests/unit/test_no_legacy_imports.py` still green (AST + path scan of `src/`). |
| 5 | At least one result bundle with schema version and provenance | Artifact path from demo: `/tmp/vms_phase0/` (or pytest tmp). Files: `request.json`, `config_snapshot.json`, `data_manifest.json`, `method_eligibility.json`, `validation_report.json`, `simulation_metadata.json`, `run_context.json` — each stamped with `run_id`, `schema_version=vms-0.2.phase0`, config/data/code hashes. Status `PHASE0_CONTRACTS_BASELINE_NOT_A_VALUATION`; labels include `INVESTMENT_VALUE_NOT_ESTABLISHED`. All method rows `NOT_RUN`. |

## Example artifact summary
```text
vms phase0 --out /tmp/vms_phase0 --seed 42
→ status=PHASE0_CONTRACTS_BASELINE_NOT_A_VALUATION
→ schema_version=vms-0.2.phase0  implemented_phase=PHASE_0
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
→ enabled_methods=0  method_status_rows=11 (catalog candidates, all NOT_RUN)
```

## Known gaps (honest)
- No profile classifier, method router, FCFF/FCFE/DDM/RIM/multiples/NAV, ensemble, or market-pricing engine (Phases 2–9).
- Method registry is **empty by design**; enabling a method without `IMPLEMENTED` is a config error.
- Observation-level `QualityStatus` in `observations.py` still uses lowercase values (`observed`, …) for VMS-0.1 data compatibility; SPEC §6.1 uppercase spellings live in `ObservationQualityStatus`. Migration of stored CSVs is deferred.
- Legacy `vms demo` still runs the 0.1 pipeline smoke; the **Phase 0** offline demo for 0.2 is `vms phase0`.
- `data_manifest.data_hash` in Phase 0 is a synthetic provenance stamp, not the full record hash used by Phase 1+.
- CI workflow remains untested remotely (no remote).
- Engineering pass ≠ investment alpha.

## Failed criteria
None. No criterion was weakened.
