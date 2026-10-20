# dsde-valuation — VMS-0.1

Standalone valuation & conditional return engine for China A-shares. Spec: [SPEC.md](SPEC.md).

**Status: Phases 0–10 complete (VMS-0.1.0 release packaging on synthetic).** Full pipeline:
contracts → PIT/quality → drivers/regimes → correlated paths → path-wise statements →
FCFF DCF + exit multiple → entry-price returns (DIVIDEND-NO-REINVEST) → sensitivity →
chronological walk-forward evaluation → optional DSDE consumer adapter.
Schema contract: `vms-0.1.0`. Labels always include `INVESTMENT_VALUE_NOT_ESTABLISHED` on
synthetic (no alpha claim). See [docs/model_card.md](docs/model_card.md),
[PHASE10_DONE.md](PHASE10_DONE.md), [RELEASE_NOTES.md](RELEASE_NOTES.md), and
[docs/assumptions.md](docs/assumptions.md).

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

Runtime deps: numpy, pandas, scipy, pydantic, pyyaml (SPEC §3.3 suggested set + YAML config),
**pyarrow**. pyarrow is justified because Phase 1 requires Parquet ingestion (§18) and §13 path outputs
use Parquet. It is the pandas Parquet engine and is never imported directly by `src/`.
Dev deps: pytest, **hypothesis** — justification: SPEC §19 mandates property-based tests
(monotonicity, seed reproducibility, posterior normalization); hypothesis is the standard tool,
is test-only and never imported by `src/`.
scipy is used from Phase 3 (Student-t quantiles in `vms.drivers.distributions`).

## Offline end-to-end demo (Phases 0–10)

```bash
# After setup above:
scripts/e2e_offline_demo.sh /tmp/vms_e2e   # lightweight path counts; writes a run bundle
# Asserts schema_version, ENGINEERING_PASS / DATA_QUALITY_PASS keys, INVESTMENT_VALUE_NOT_ESTABLISHED.
```

Python facade:

```python
from vms import ValuationEngine, ValuationRunResult
from vms.adapters.dsde import consumer_view_from_result, dsde_availability
# eng.run(request, data_bundle, config) -> ValuationRunResult
# dsde_availability()["dsde_present"] may be False; core still works.
```

## CLI

```bash
vms validate-data --input <dir> [--as-of 2026-06-30] [--ticker ID]       # schema; + PIT/quality gates with --as-of
vms build-snapshot --input <dir> --ticker 000001.SZ --as-of 2026-06-30 --out runs/snap
vms project --input <dir> --ticker 000001.SZ --as-of 2026-06-30 --out runs/proj [--years 5] [--policy ID]
vms value --input <dir> --ticker 000001.SZ --as-of 2026-06-30 --out runs/val [--paths N] [--seed 42]
vms returns --input <dir> --ticker 000001.SZ --as-of 2026-06-30 --out runs/ret [--spot-price S] [--horizons 1,3,5] [--paths N] [--seed 42]
vms sensitivity --run-dir runs/ret [--run-id ...] [--paths N]  # writes sensitivity_report.json
vms evaluate --universe config/universe.synthetic.yaml --start 2018-01-01 --end 2022-12-31 --out runs/eval
vms project-paths --input <dir> --ticker 000001.SZ --as-of 2026-06-30 --out runs/fp [--paths N] [--policy ID]
vms simulate --input <dir> --ticker 000001.SZ --as-of 2026-06-30 --out runs/sim [--paths N] [--seed 42]
vms estimate --input <dir> --ticker 000001.SZ --as-of 2026-06-30 --out runs/est [--seed 42]  # regimes + distributions
vms demo --out runs/demo --seed 42 [--format csv|parquet] [--as-of ...] [--policy ID]  # SYNTHETIC smoke, no valuation
# gate options: --mode production|exploratory  --override-reason "..."  --config path
```
Valuation requires explicit `valuation.risk_free_rate` in config (never invented).
Date-only `--as-of` = 15:00:00 Asia/Shanghai (rule ASOF-DATE-CLOSE-v1).
Exit codes: `0` ok, `1` unexpected error, `2` invalid input/config/args (incl. `regimes.model: hmm`, interface only — REGIME-HMM-DEFERRED-v1), `3` BLOCKED by critical
data-quality errors in production mode (incl. missing industry classification, INDUSTRY-UNCLASSIFIED-v2), `4` UNSUPPORTED_PROFILE (e.g. banks/non-bank financials),
`5` projection INSUFFICIENT_DATA or REJECTED by an accounting invariant.
Policies: `conservative_baseline` (default), `historical_continuation`, `fixed_payout`, `target_leverage`,
`min_cash_excess_distribution` (config `capital_allocation`).

Leakage mutation check: `scripts/leakage_mutation_check.sh`. It injects 4 PIT-filter leaks, a walk-forward
origin leak and a regime-inference leak, and requires `tests/leakage` to fail on each. Invariant mutation check: `scripts/invariant_mutation_check.sh`.
It injects 7 typical modelling bugs into the projection engine and requires each one to be REJECTED.

## Layout
`src/vms/<module>/` follows SPEC §17. All listed modules are implemented through Phase 10,
including optional `vms.adapters.dsde`.
