# Phase 0 — completion report (VMS-0.1 §18, reported per §21)

Date: 2026-10-20 (Asia/Shanghai). Repo: local git only, no remote.
Status: **all Phase 0 acceptance criteria pass.** This is `ENGINEERING_PASS` for Phase 0 only; no
valuation exists and nothing here bears on investment value.

## Changed files (all new)
```
.gitignore  .github/workflows/ci.yml  pyproject.toml  requirements.lock  README.md  SPEC.md  PHASE0_DONE.md
config/default.yaml  config/driver_profiles/operating_company.yaml
docs/architecture.md  docs/data_contracts.md  docs/model_card.md(placeholder)
examples/synthetic_operating_company/{README.md,generate_data.py}
src/vms/__init__.py  src/vms/seeding.py
src/vms/schemas/{__init__,observations,config,errors}.py
src/vms/data/{__init__,io,synthetic}.py
src/vms/reporting/{__init__,metadata}.py
src/vms/cli/{__init__,main,__main__}.py
src/vms/{pit,quality,drivers,regimes,sampling,statements,capital_allocation,valuation,
         equity_bridge,returns,diagnostics,evaluation}/__init__.py   (empty, "NOT IMPLEMENTED (Phase N)")
tests/conftest.py
tests/unit/{test_schemas,test_config,test_seeding_metadata,test_no_legacy_imports,test_package_skeleton}.py
tests/integration/test_cli.py   tests/property/test_properties.py
tests/leakage/README.md  tests/evaluation/README.md   (empty until Phase 1 / 9)
```

## Tests executed
| Environment | Command | Result |
|---|---|---|
| Fresh `git clone` → new `.venv` (Python 3.11.17) → `uv pip sync requirements.lock` → `pip install -e . --no-deps` | `python -m pytest` | **124 passed** (unit 109, integration 12, property 3) |
| Repo `.venv` (Python 3.13.5) | `python -m pytest` | **124 passed** |

## Evidence per acceptance criterion
1. **Clean environment installs and runs tests** — fresh clone + new 3.11 venv from the lock file, 124/124
   pass (table above). CI file `.github/workflows/ci.yml` runs the same steps on 3.11/3.12/3.13 (file only, not executed remotely).
2. **Invalid schema/config/timestamp/unit fails with actionable errors** — `tests/unit/test_schemas.py`
   (naive `published_at`/`ingested_at`/`timestamp`/`as_of`; bad currency; bad unit; bad statement_type;
   bad quality_status; NaN/Inf; null-vs-status consistency; published before period_end; ranges for
   paths/horizons/spot/seed; extra/missing fields), `tests/unit/test_config.py` (12 config and 7 profile
   mutations; messages must contain file path + field path + expected value), `tests/integration/test_cli.py`
   (CSV rows report `file:line N: field: message`; CLI exit code 2). Example:
   ```
   $ vms demo --out /tmp/x --as-of 2025-06-30T15:00:00
   error: --as-of '2025-06-30T15:00:00' is timezone-naive; append an offset such as +08:00   (exit 2)
   $ vms demo --out /tmp/x --config /tmp/badcfg/default.yaml
   error: invalid config
   /tmp/badcfg/default.yaml: base_currency: Input should be 'CNY' (got 'USD')
   /tmp/badcfg/default.yaml: monte_carlo.default_paths: Input should be greater than 0 (got -3)   (exit 2)
   ```
3. **Same inputs/config/seed reproduce synthetic outputs within tolerance** —
   `test_same_inputs_reproduce_identical_artifacts` compares sha256 of all deterministic artifacts + data CSVs
   (byte-identical; a different seed changes data and run_id). `test_config_change_changes_config_hash`,
   property tests on seed streams and synthetic data, pinned RNG values. Manual: two `vms demo` runs gave
   identical sha256 for all 6 files. Cross-interpreter: data_hash `850bbf761083f2c5…` and config_hash
   `213f2de2b3865896…` identical on Python 3.11 and 3.13.
4. **No legacy imports** — `tests/unit/test_no_legacy_imports.py`: AST scan of `src/` for
   `dsde_engine/dsde/pit/ftd/dv1/fundamental_mc/legacy` top-level imports, text scan for `dsde-engine`,
   `/workspace/dsde`, `sys.path` hacks, and an allow-list of third-party imports
   (numpy/pandas/scipy/pydantic/yaml); includes a self-test that the detector catches a violation.
5. **Offline synthetic demo works** — `vms demo --out runs/demo --seed 42` (no network, no credentials)
   writes `request.json, config_snapshot.json, data_manifest.json, simulation_metadata.json,
   run_context.json, data/*.csv`, all with shared `run_id` and `schema_version=vms-0.1.phase0`,
   status `PHASE0_SMOKE_NOT_A_VALUATION`. Tested via the installed console script in `test_demo_via_console_script`.

## Known limitations (honest)
- No valuation, PIT filtering, quality gates, drivers, sampling, DCF or returns — later phases.
  `vms value/build-snapshot/sensitivity/evaluate` intentionally not registered.
- `validate-data` is schema-only; `--as-of` just counts post-as_of records (informational).
- Driver-profile bounds are hand-set sanity limits (`bounds_status: placeholder`), not estimates.
  `unsupported_industries` is declared but not yet enforced (Phase 2).
- Config fields for Phases 4–7 (terminal value, returns, entry grid, invalid-path threshold) are
  validated but unused. Values are labeled assumptions.
- No FX conversion to CNY; HKD/USD accepted at schema level only.
- run_id includes the git SHA, so it changes with every commit (by design); `src_dirty` flags uncommitted src changes.
- Reproducibility "tolerance" for Phase 0 is exact bytes on the same lock; MC tolerances come with Phase 4.
- `vms demo` writes the synthetic data directory before building the request, so an invalid `--paths`
  leaves `data/` behind (exit 2, no metadata artifacts written).
- scipy is locked but not yet imported.
- CI workflow is untested remotely (there is no remote).
