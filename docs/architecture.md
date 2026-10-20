# Architecture (state at Phase 2)

Target pipeline: SPEC §4 (adapters → PIT store → gates → drivers → regimes → sampler →
statements → capital allocation → DCF/multiples → equity bridge → per-share value →
entry-price-conditioned returns → diagnostics → result bundle).

## What exists now

| Component | Location | Status |
|---|---|---|
| Data contracts | `vms.schemas.observations` | Implemented (§5.3) |
| Config + driver-profile schema/loader | `vms.schemas.config` | Implemented; most fields consumed only in later phases |
| Validation error formatting | `vms.schemas.errors` | Implemented |
| Canonical field registry FIELDS-2 | `vms.schemas.fields` | Implemented (flow/stock, sign conventions) |
| CSV/Parquet ingestion (canonical schema only) | `vms.data.io` | Implemented; no provider adapters |
| SYNTHETIC data source | `vms.data.synthetic` | Seeded; cumulative YTD flows, restatement, late publication, bonus share + dividend (with revision), vendor 前复权 prices |
| as_of rule ASOF-DATE-CLOSE-v1 | `vms.pit.asof` | Implemented |
| PIT snapshot builder | `vms.pit.snapshot` | Implemented (known-at filtering, versions, cumulative→standalone, PIT price adjustment) |
| Integrity checks + issue catalogue | `vms.quality.checks`, `vms.quality.issues` | Implemented; EV bridge DEFERRED (Phase 6) |
| Quality report + production gate | `vms.quality.report` | Implemented (PASS / PASS_WITH_WARNINGS / BLOCKED / PIT_INCOMPLETE; exploratory override) |
| Deterministic seeding | `vms.seeding` | Implemented (PCG64, named SeedSequence sub-streams) |
| Run metadata + hashing + artifact writer | `vms.reporting.metadata` | Implemented |
| Assumption register | `vms.assumptions` | Implemented; mirrored in docs/assumptions.md |
| Annual history + driver definitions/transforms/estimates | `vms.drivers.history/definitions/transforms/estimate` | Deterministic central values only (distributions: Phase 3) |
| Sector-profile plug-in interface | `vms.drivers.profiles` | `SectorProfile` ABC + registry; `operating_company` profile; config-driven UNSUPPORTED_PROFILE |
| Deterministic statements, tax-loss pools, invariants, FCFF/FCFE types | `vms.statements` | Implemented (§9) |
| Capital-allocation policies | `vms.capital_allocation.policies` | 5 versioned policies (§10) |
| Phase 2 pipeline | `vms.pipeline.run_projection` | assess → gate → profile → drivers → policy → projection |
| CLI | `vms.cli.main` | `validate-data [--as-of]`, `build-snapshot`, `project`, `demo` (smoke) |
| regimes, sampling, valuation, equity_bridge, returns, diagnostics, evaluation | `vms.<module>` | Empty packages — Phases 3–9 |

## Reproducibility design (§8.3)

- **Seeding:** `make_rng(seed)` → `Generator(PCG64(SeedSequence(seed)))`. `stream_rng(seed, name)`
  derives an independent sub-stream with `spawn_key = sha256(name)[:8]`, so adding a new stream
  never perturbs existing ones. A test pins sample values to detect accidental scheme changes.
- **Hashes:** `data_hash` = sha256 over sorted canonical-JSON records (row-order independent);
  `config_hash` = sha256 of canonical JSON of the validated config + resolved driver profile;
  `request_hash` likewise.
- **Code version:** `git rev-parse HEAD` + `src_dirty` flag (uncommitted changes under `src/`);
  `"unknown"` outside a git checkout.
- **run_id:** content-addressed `vms-<sha256(request, config, data, git sha, schema)[:16]>`.
  Identical inputs ⇒ identical run_id. Wall-clock time lives only in `run_context.json`, which
  is excluded from the deterministic artifact set
  (`request.json`, `config_snapshot.json`, `data_manifest.json`, `simulation_metadata.json`).
- **Tolerance:** Phase 0 artifacts are reproduced byte-for-byte (same platform/lock). Numerical
  tolerances for Monte Carlo statistics will be defined with the sampler (Phase 4).

## Boundaries
- No imports from `dsde-engine` or other legacy code; DSDE adapter is Phase 10 and optional.
- All artifacts carry `run_id` and `schema_version` (`vms-0.1.phase2`).

## Phase 1 data flow
```
CSV/Parquet + sources.yaml ──load_directory──▶ LoadResult (schema-validated records)
      └─assess(as_of, instrument)─▶ build_snapshot (known-at ≤ as_of only) ─▶ PITSnapshot
                                     └─ run_checks(snapshot, known records, config.quality)
                                        ─▶ DataQualityReport ─▶ gate(): production+BLOCKED ⇒ exit 3
```
- **Leakage guarantee:** `build_snapshot` filters every table by its known-at time *before* any
  processing. The only post-as_of information that reaches any output is the count of excluded
  records (`excluded_post_as_of`, INFO issue). It is deliberately kept out of `pit_snapshot.json`.
- **Data hash** is instant-normalised (UTC), so CSV (+08:00) and Parquet (stored in Asia/Shanghai)
  inputs with identical content hash identically.

## Phase 2 flow (deterministic central case; not a valuation)
```
LoadResult ─assess─▶ PITSnapshot + report ─gate─▶ resolve_profile(snapshot.classification, config.industry)
   ├─ UNSUPPORTED_PROFILE ⇒ annual history only, no drivers/statements (CLI exit 4)
   └─ SectorProfile (registry) ─validate_driver_profile─▶ estimate_drivers(history) ─▶ DriverModel
        └─ make_policy(capital_allocation) ─▶ profile.project(...) ─▶ Ledger[item@year → TracedValue]
             └─ check_invariants (independent recomputation) + unresolved_refs ⇒ VALID | REJECTED(codes)
```
- **Plug-in profiles:** a sector is added by registering a `SectorProfile` subclass and mapping
  industries to it in `config.industry.profile_map`. No sector conditionals exist in code; a test greps `src/`
  for sector names. Banks/non-bank financials are UNSUPPORTED by config list (INDUSTRY-SW-L1-v1).
- **Traceability:** every projected item is a write-once `TracedValue(value, formula, inputs)`.
  The inputs are other items (`item@year`), `driver:`, `policy:`, `config:`, `assumption:`, `corporate_action:` or
  `snapshot:` references to the exact PIT record version. Unresolvable references reject the projection.
- **Order (§9.1):** revenue → gross profit → EBIT (margin; opex implied) → D&A → interest (opening
  debt) → pre-tax → book tax with loss pool → NI / minority / parent NI → NWC → capex/acquisitions →
  operating tax with its own loss pool → NOPAT → FCFF → CFO → policy (dividends, buybacks, issuance, debt) →
  revolver to min cash → cash, debt, equity, balance sheet → FCFE → shares.
- **FCFF vs FCFE:** distinct pydantic types (`kind` literal); `present_value` accepts only
  FCFF+WACC or FCFE+CostOfEquity, and arithmetic between series raises `CashFlowTypeError`.
