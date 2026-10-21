# dsde-valuation — VMS-0.2

Adaptive Multi-Method valuation & conditional return engine for China A-shares.
Spec: [SPEC.md](SPEC.md) (VMS-0.2). Archived VMS-0.1: [SPEC_VMS-0.1.md](SPEC_VMS-0.1.md), tag `vms-0.1`.

**Status: VMS-0.2 Phase 9 complete (market-pricing regime + exit-price engine; Phase 8 ensemble retained).**
Schema contract: `vms-0.2.phase9`. Package: `0.2.0a0`. Phase report: [PHASE9_DONE.md](PHASE9_DONE.md) (see also [PHASE8_DONE.md](PHASE8_DONE.md)…[PHASE0_DONE.md](PHASE0_DONE.md)).
Labels always include `INVESTMENT_VALUE_NOT_ESTABLISHED` on synthetic (no alpha claim).

Phase 6 methods live under `vms.methods.rim` / `nav` / `sotp`; multiples under `vms.methods.multiples`;
cash-flow under `vms.methods.cash_flow`. Legacy `vms value` (0.1 FCFF pipeline) remains importable
but is **not** the adaptive path. Ensemble lives under `vms.ensemble` (PRIOR_ONLY research
mixture only — never `ENSEMBLE_CALIBRATED` without OOS). Exit-price engine is Phase 9; return-grid polish is Phase 10.
Older `PHASE*_DONE.md` from VMS-0.1 numbering are historical only where superseded.

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


## Offline Phase 0 demo (VMS-0.2 contracts)

```bash
vms phase0 --out /tmp/vms_phase0 --seed 42
vms phase3 --out /tmp/vms_phase3 --seed 42 --paths 80   # path bundle; NOT a valuation
vms phase4 --out /tmp/vms_phase4 --seed 42 --paths 40   # FCFF/FCFE/DDM via router; NOT investment advice
vms phase5 --out /tmp/vms_phase5 --seed 42 --multiples-only  # P/E P/B EV/* + PIT peers; NOT investment advice
vms phase6 --out /tmp/vms_phase6 --seed 42 --fixture financial  # RIM/NAV/SOTP; NOT investment advice
vms phase7 --out /tmp/vms_phase7 --seed 42 --fixture mature     # router + disagreement; NOT investment advice
vms compare-methods --out /tmp/vms_compare --fixture mature     # method_comparison.json; no blend
vms phase8 --out /tmp/vms_phase8 --seed 42 --fixture mature     # ensemble PRIOR_ONLY + L1O; NOT investment advice
vms phase9 --out /tmp/vms_phase9 --seed 42 --paths 40           # market-pricing + exit prices; NOT investment advice
# or:
python examples/synthetic_mature_operating/run_phase0.py --out /tmp/vms_phase0 --seed 42
```

Writes a provenance bundle (`request.json`, `config_snapshot.json`, `method_eligibility.json`
with all methods `NOT_RUN`, `simulation_metadata.json`, …). **Not a valuation.**

## Phase 2 profile / route (NOT a valuation)

```bash
vms profile --fixture examples/profile_fixtures/mature_operating.json
vms route --fixture examples/profile_fixtures/financial_institution.json --target FUNDAMENTAL_VALUE_CURRENT --attempt-stubs
```

Five synthetic fixtures under `examples/profile_fixtures/` exercise mature, growth/neg-FCF,
bank, cyclical and holding profiles. Router lists hard-gate outcomes only; no method math.
Labels: `INVESTMENT_VALUE_NOT_ESTABLISHED`.

## Real A-share ingest (optional HiThink + Eastmoney NOTICE)

Core / synthetic path never requires DuckDB or live HiThink. Optional extra:

```bash
uv pip install --python .venv/bin/python 'dsde-valuation[hithink]'   # duckdb + requests
# Env (defaults shown):
#   HITHINK_FUND_DB_PATH=/workspace/data/hithink_fundamentals.duckdb
#   MARKETDB_DB_PATH=/workspace/data/market.duckdb
#   HITHINK_FUND_LIB=/workspace/data/hithink_fund
```

```bash
vms ingest-hithink --ticker 600519.SH --out data/600519 --prefer-local
vms build-snapshot --input data/600519 --ticker 600519.SH --as-of 2025-06-30 --out runs/snap \
  --mode exploratory --override-reason "industry unset / LATEST_ONLY PIT"
# Convenience: ingest+snapshot
vms build-snapshot --provider hithink --ticker 600519.SH --as-of 2025-06-30 --out runs/snap \
  --mode exploratory --override-reason "hithink_smoke"
```

PIT `published_at` = Eastmoney NOTICE_DATE (HITHINK-PIT-NOTICE-v1). Source is `LATEST_ONLY` →
`pit_complete=false`. Never puts vendor qfq into `adjusted_close`. See
[docs/data_contracts.md](docs/data_contracts.md), [docs/model_card.md](docs/model_card.md),
[PHASE_REALDATA_DONE.md](PHASE_REALDATA_DONE.md).

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
