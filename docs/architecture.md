# Architecture (state at Phase 9)

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
| Annual history + driver definitions/transforms/estimates | `vms.drivers.history/definitions/transforms/estimate` | Deterministic central values (Phase 2 projection) |
| Fundamental regimes | `vms.regimes` | Rule-based soft classifier FUND-RULES (PIT fundamentals only), Dirichlet transitions, HMM interface NOT_IMPLEMENTED, market regime UNAVAILABLE |
| Driver distributions | `vms.drivers.distributions` | DRIVER-DIST-1: robust shrunk location/scale in transformed space, regime-conditional Student-t mixture, empirical, bootstrap parameter uncertainty |
| Walk-forward | `vms.drivers.walk_forward` | WF-1: rolling origin, past-only snapshots, pinball/coverage/Brier, selection by out-of-sample pinball |
| Sector-profile plug-in interface | `vms.drivers.profiles` | `SectorProfile` ABC + registry; `operating_company` profile; config-driven UNSUPPORTED_PROFILE |
| Deterministic statements, tax-loss pools, invariants, FCFF/FCFE types | `vms.statements` | Implemented (§9) |
| Capital-allocation policies | `vms.capital_allocation.policies` | 5 versioned policies (§10) |
| Phase 2 pipeline | `vms.pipeline.run_projection` | assess → gate → profile → drivers → policy → projection |
| Phase 3 pipeline | `vms.pipeline.run_estimation` | assess → gate → profile → regimes → walk-forward → distributions |
| CLI | `vms.cli.main` | `validate-data [--as-of]`, `build-snapshot`, `project`, `estimate`, `demo` (smoke) |
| sampling, valuation, equity_bridge, returns, diagnostics, evaluation | `vms.<module>` | Empty packages — Phases 4–9 |

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
- All artifacts carry `run_id` and `schema_version` (`vms-0.1.phase9`).

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

## Phase 3 flow (regimes + driver distributions; not a valuation)
```
PITSnapshot.financials ─fundamental_features─▶ TTM growth / TTM recurring EBIT margin / Δmargin (known_at ≤ as_of)
   └─ RuleBasedClassifier.filter (soft logistic rules, forward filter only) ─▶ per-period posteriors
        ├─ current posterior (FundamentalRegimePosterior, kind=FUNDAMENTAL)
        └─ estimate_transitions (annual-step soft counts + Dirichlet prior) ─▶ next-year state probabilities
MarketRegimePosterior (kind=MARKET) = UNAVAILABLE (no source configured; never derived from fundamentals)
AnnualHistory ─observations(z = transform(x), clipped to bounds)─▶ fit_specs: prior_only | pooled_t |
   pooled_empirical | regime_t (+ naive_last benchmark)
walk_forward: for each FY y with ≥ min_train_years: rebuild snapshot at first publication of FY y
   (past-only), refit regimes + specs, score FY y+1 (pinball, coverage; regime Brier) ─▶ selection
build_distribution_model: full-history fits + seeded bootstrap of the estimator + selected spec
```
- **No returns/prices in regimes:** `infer_regimes(financials, as_of, cfg)` receives snapshot financials only;
  an AST test forbids price/return identifiers in `vms.regimes`, and perturbation tests show regimes,
  distributions and walk-forward are invariant to prices and to anything published after as_of.
- **Selection:** argmin mean walk-forward pinball (transformed space) when ≥ `min_origins` scored origins,
  else the configured default with `SELECTION_DEFAULT_INSUFFICIENT_ORIGINS`. In-sample pinball is reported
  only (a test corrupts it and checks selection is unchanged).
- **Not yet:** dependence between drivers, joint sampling (Phase 4); central case still uses Phase 2 medians.

## Phase 4 flow (correlated paths; not a valuation)
```
DistributionModel + RegimeResult
  ├─ estimate_dependence: residual Pearson → shrink to I (DRIVER-DEPENDENCE-v1); material blocks recorded
  ├─ central path: argmax state path + selected-spec loc (CENTRAL-FROM-SELECTED-v1)
  └─ for path i = 0..N-1 (stream path:<i>):
       sample bootstrap params → Dirichlet transition matrix → initial state
       → each year: transition → Gaussian-copula Student-t shocks → margins (selected family)
       → persistence_t uses lag z → clip/repair constraints → accept or InvalidPathSummary
MCDiagnostics: key stats + MCSE + same-seed stability; provenance hashes persisted
```
- CLI: `vms simulate` writes `simulation_bundle.json` (+ `paths.parquet` when >500 paths) and refreshes
  `simulation_metadata.json`. Facade: `ValuationEngine.simulate_paths`.

## Phase 5 flow (path-wise statements; not a valuation)
```
SimulationBundle.paths (+ central)
  └─ for each path: OperatingCompanyProfile.project(..., year_drivers=path.year→drivers)
       └─ same §9 order / Phase 2 policies / check_invariants
            ├─ VALID → included in aggregates (fcff, shares, fcff_per_share, ...)
            └─ REJECTED / INSUFFICIENT_DATA → recorded with reason codes; EXCLUDED_FROM_AGGREGATES

## Phase 6 flow (DCF + exit-multiple + bridge; not a return product)
```
FinancialPathBundle (VALID paths only)
  ├─ build_wacc(rf REQUIRED, erp, beta shrink-to-prior, kd, tc, weights)
  ├─ dcf_fcff: PV(FCFF)+Gordon TV; reject WACC_G_MARGIN_FAIL (no silent repair)
  ├─ exit_multiple_ev: separate EV (robust peer multiple or explicit)
  └─ bridge_ev_to_equity: +cash −debt −leases −minority −other; VPS; negative equity preserved
Aggregates over valid DCF paths; path_valuations.parquet + valuation_summary.json

## Phase 7 flow (entry-price returns; not sensitivity attribution)
```
ValuationBundle + FinancialPathBundle + spot
  ├─ entry grid: spot × relative_to_spot (ENTRY-PRICE-GRID-v1)
  ├─ per path × horizon H: EquityValue_H from remaining FCFF PV + TV @ H (HORIZON-EQUITY-REMAINING-PV-v1)
  ├─ cum DPS without reinvestment (DIVIDEND-NO-REINVEST-v1)
  ├─ R=(VPS_H + cum_DPS - P0)/P0; ann geo (1+R)^(1/H)-1
  └─ mixture + regime-conditional stats (CVaR, hurdles, MCSE); price×regime invariant
return_distribution_summary.json + path_returns.parquet

## Phase 8 flow (sensitivity / attribution; not walk-forward eval)
```
Baseline Phase 7 run (frozen paths where possible)
  ├─ OAT: single driver shock on paths OR single valuation/policy/posterior/transition input
  ├─ Joint: growth+margin; capex+WC; WACC+g
  ├─ Ablation attribution (pathwise → central year-1)
  ├─ Process vs parameter (parameter_mode fixed vs resampled)
  ├─ DCF vs exit-multiple comparison; TV fraction + g-shock
  └─ Tail metrics: Δ mean return, Δ p_loss, Δ CVaR (MC percentile ≠ CI)
sensitivity_report.json (reproducible content_hash)

## Phase 9 flow (walk-forward evaluation; not DSDE adapter)
```
Universe (synthetic offline OK)
  for each instrument, chronological FY origin in [start, end]:
    reconstruct PIT @ origin (past-only)
    persist forecasts BEFORE outcomes (CF / IV / price / TSR + baselines)
    if horizon elapsed: realize outcomes; score separately
  exclude PIT_INCOMPLETE from unbiased metrics
  labels: ENGINEERING / DATA_QUALITY / CALIBRATION / INVESTMENT_VALUE_NOT_ESTABLISHED (synthetic)
evaluation_report.json + forecasts/
Random splits => RandomSplitProhibitedError
