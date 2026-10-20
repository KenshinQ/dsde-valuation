# Architecture (VMS-0.1 / Phase 10 release)

Target pipeline: SPEC §4 (adapters → PIT store → gates → drivers → regimes → sampler →
statements → capital allocation → DCF/multiples → equity bridge → per-share value →
entry-price-conditioned returns → diagnostics → result bundle → optional DSDE consumer view).

## End-to-end flow

```
CSV/Parquet (+ SYNTHETIC)
  → load_directory → LoadResult
  → assess / PITSnapshot + DataQualityReport
  → sector profile resolve (UNSUPPORTED_PROFILE short-circuit)
  → regimes + driver distributions (walk-forward selection)
  → SimulationBundle (Gaussian copula)
  → FinancialPathBundle (path-wise statements + capital allocation)
  → ValuationBundle (FCFF DCF + exit multiple + EV-equity bridge)
  → ReturnDistributionBundle (entry-price × horizon × regime mixture)
  → optional SensitivityReport
  → ValuationRunResult (schema_version=vms-0.1.0)
  → optional DSDEConsumerView (vms.adapters.dsde)  [DSDE package NOT required]
```

Facade: `ValuationEngine.run(request, data_bundle, config) -> ValuationRunResult`.

CLI path (offline demo): `scripts/e2e_offline_demo.sh` runs
validate → snapshot → estimate → simulate → project-paths → value → returns →
sensitivity → evaluate with lightweight path counts.

## Component status (all Phases 0–10)

| Component | Location | Status |
|---|---|---|
| Data contracts | `vms.schemas.*` | Implemented |
| Config + profiles | `vms.schemas.config` | Implemented |
| Ingestion + SYNTHETIC | `vms.data` | Implemented; **no live provider adapter** |
| PIT + quality gates | `vms.pit`, `vms.quality` | Implemented |
| Drivers / regimes / WF | `vms.drivers`, `vms.regimes` | Implemented (HMM deferred) |
| Sampler | `vms.sampling` | Implemented |
| Statements + capital alloc | `vms.statements`, `vms.capital_allocation` | Implemented |
| Valuation + equity bridge | `vms.valuation`, `vms.equity_bridge` | Implemented |
| Returns | `vms.returns` | Implemented (DIVIDEND-NO-REINVEST) |
| Diagnostics | `vms.diagnostics` | Implemented |
| Evaluation | `vms.evaluation` | Chronological only |
| Reporting / seeding | `vms.reporting`, `vms.seeding` | Implemented |
| Optional DSDE adapter | `vms.adapters.dsde` | Implemented; DSDE absent = no-op |
| Public run result | `vms.result.ValuationRunResult` | Implemented |
| Facade | `vms.engine.ValuationEngine` | Full `run` orchestration |

## Supported vs unsupported profiles

**Supported:** `operating_company` (generic non-financial FCFF).

**Unsupported (config `sector_profiles.unsupported`):** banks, insurance, brokerages, and any
industry listed as unsupported → `UNSUPPORTED_PROFILE` (no projection/DCF). Documented in
`docs/model_card.md`.

## Reproducibility (§8.3)

- PCG64 SeedSequence named sub-streams; content-addressed `run_id`.
- Artifacts stamped with `run_id` + `schema_version` (`vms-0.1.0`).
- Leakage + invariant mutation checks in `scripts/`.

## Boundaries

- No imports from `dsde-engine` or legacy PIT/FTD/DV1 (tested).
- DSDE integration only via `vms.adapters.dsde` documented interface.
- HiThink / live A-share provider adapters are **future work** (not Phase 10).
- No alpha / investability claim without predeclared leakage-safe OOS evidence.
