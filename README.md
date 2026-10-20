# dsde-valuation — VMS-0.1

Standalone valuation & conditional return engine for China A-shares. Spec: [SPEC.md](SPEC.md).

**Status: Phase 0 only** (contracts, config validation, run metadata, deterministic seeding,
offline smoke demo). There is **no valuation logic yet**; `vms demo` output is labeled
`PHASE0_SMOKE_NOT_A_VALUATION`. See [PHASE0_DONE.md](PHASE0_DONE.md).

Fully standalone: does not import `dsde-engine` or any legacy PIT/FTD/DV1/Monte-Carlo code
(enforced by `tests/unit/test_no_legacy_imports.py`).

## Setup (clean environment)

```bash
uv venv .venv --python 3.11          # any 3.11+; box uses 3.13
uv pip sync --python .venv/bin/python requirements.lock
uv pip install --python .venv/bin/python --no-deps -e .
.venv/bin/python -m pytest
```

Without uv: `python -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e .`

### Dependency lock
`requirements.lock` is generated from `pyproject.toml` (runtime + `dev` extra), resolved for the
Python 3.11 floor:

```bash
uv pip compile pyproject.toml --extra dev --python-version 3.11 -o requirements.lock
```

Runtime deps: numpy, pandas, scipy, pydantic, pyyaml (SPEC §3.3 suggested set + YAML config).
Dev deps: pytest, **hypothesis** — justification: SPEC §19 mandates property-based tests
(monotonicity, seed reproducibility, posterior normalization); hypothesis is the standard tool,
is test-only and never imported by `src/`.
scipy is locked but not yet imported (first use expected in Phase 3/4 distributions).

## CLI

```bash
vms validate-data --input <dir> [--as-of 2026-06-30]   # schema validation only (Phase 0)
vms demo --out runs/demo --seed 42 [--paths N] [--horizons 1,3,5] [--as-of ISO8601+08:00]
```
Exit codes: `0` ok, `2` invalid input/config, `1` unexpected error.
`build-snapshot`, `value`, `sensitivity`, `evaluate` (SPEC §16.2) are not registered until
their phases are implemented.

## Layout
`src/vms/<module>/` follows SPEC §17. Modules for later phases exist as empty packages whose
docstring says `NOT IMPLEMENTED (Phase N)`; a test enforces that they export nothing.
