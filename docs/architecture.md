# Architecture (state at Phase 0)

Target pipeline: SPEC §4 (adapters → PIT store → gates → drivers → regimes → sampler →
statements → capital allocation → DCF/multiples → equity bridge → per-share value →
entry-price-conditioned returns → diagnostics → result bundle).

## What exists now

| Component | Location | Status |
|---|---|---|
| Data contracts | `vms.schemas.observations` | Implemented (§5.3) |
| Config + driver-profile schema/loader | `vms.schemas.config` | Implemented; most fields consumed only in later phases |
| Validation error formatting | `vms.schemas.errors` | Implemented |
| CSV loader (schema-only) | `vms.data.io` | Implemented; **no** PIT filtering/dedup/gates |
| SYNTHETIC data source | `vms.data.synthetic` | Implemented, seeded, labeled `SYNTHETIC` |
| Deterministic seeding | `vms.seeding` | Implemented (PCG64, named SeedSequence sub-streams) |
| Run metadata + hashing + artifact writer | `vms.reporting.metadata` | Implemented |
| CLI | `vms.cli.main` | `validate-data`, `demo` (smoke) |
| pit, quality, drivers, regimes, sampling, statements, capital_allocation, valuation, equity_bridge, returns, diagnostics, evaluation | `vms.<module>` | Empty packages — Phases 1–9 |

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
- All artifacts carry `run_id` and `schema_version` (`vms-0.1.phase0`).
