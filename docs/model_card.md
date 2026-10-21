# VMS-0.2 Model Card

| Field | Value |
|---|---|
| Package | `dsde-valuation` / `vms` |
| Version | `0.2.0rc1` (pre-release; calibration insufficient) |
| Schema contract | `vms-0.2.phase12` |
| Spec | [SPEC.md](../SPEC.md) (VMS-0.2) |
| Status | **Engineering release on synthetic data only** |
| Investment label | `INVESTMENT_VALUE_NOT_ESTABLISHED` — **never** `INVESTMENT_VALUE_SUPPORTED` without predeclared leakage-safe OOS evidence |

This card satisfies SPEC §19 / §20 Phase 12. Engineering success is **not** investment alpha (SPEC §2.12, §22.16).

## 1. Intended use

VMS-0.2 is a **standalone** Adaptive Multi-Method valuation and conditional-return engine for China A-share research workflows. Given a point-in-time information set and configuration, it:

- classifies a company economic profile and routes eligible valuation methods;
- produces **method-specific** value distributions (FCFF/FCFE/DDM, multiples, RIM, NAV/SOTP where gated);
- keeps fundamental value separate from future market exit prices;
- builds entry-price-conditioned total-return distributions (Track B);
- emits walk-forward / sensitivity diagnostics when requested;
- optionally exports distributions through `vms.adapters.dsde` (DSDE **not** required for the core).

Intended consumers: quantitative research engineers integrating with a decision layer (e.g. DSDE), and offline synthetic acceptance / regression.

## 2. Supported profiles (synthetic / engineering)

| Profile | Status | Typical methods (after hard gates) |
|---|---|---|
| `MATURE_OPERATING` | Supported (synthetic paths) | FCFF/FCFE/DDM; EV/EBIT, EV/EBITDA, P/E when peers pass |
| `GROWTH_OR_REINVESTMENT_HEAVY` | Partial | Routing + relative (e.g. EV/Sales) candidates; trailing P/E often ineligible |
| `FINANCIAL_INSTITUTION` | Supported (RIM path) | Residual income / P/B-style; **industrial FCFF/EV-EBITDA defaults disabled** |
| `CYCLICAL_OPERATING` | Routing supported | Unnormalized trailing P/E downgraded; mid-cycle normalization required for meaningful multiples |
| `HOLDING_OR_CONGLOMERATE` | Partial | SOTP/NAV when segment/asset schedules present; otherwise explicit data-gap / unsupported |
| Distressed / turnaround / opaque | Unsupported | Hard-gated; no silent default DCF |

Offline fixtures: `examples/profile_fixtures/` and `examples/synthetic_*`.

## 3. Unsupported profiles / out of scope

- Live trading, portfolio construction, Kelly / position sizing, execution.
- Guaranteed convergence of price to intrinsic value.
- Production calibrated ensemble (`ENSEMBLE_CALIBRATED`) without OOS protocol.
- Claiming `INVESTMENT_VALUE_SUPPORTED` on synthetic or unit-test evidence.
- Opaque LLM routing without logged deterministic rules.
- Legacy PIT/FTD/DV1 / `dsde-engine` imports (forbidden; tested).
- HMM market regimes (`regimes.model: hmm`) — interface only.
- Automatic FX conversion; non-CNY amounts blocked.

## 4. Limitations

- Real A-share PIT history is often incomplete (`pit_complete=false` on live ingest); production claims require explicit PIT completeness.
- Discount rates / ERP / terminal growth in default config are **labeled assumptions**, not calibrated market quotes.
- Terminal value can dominate EV in DCF paths; high TV fraction is warned, not “fixed” by more Monte Carlo paths.
- Peer multiples need PIT membership; current-universe backtests are gated against leakage.
- Holding-company NAV/SOTP quality depends on segment schedules; missing schedules → structured unsupported, not invented NAV.
- Cyclical mid-cycle earnings models are diagnosed in routing; full normalized-earnings engine coverage is incomplete vs SPEC §12.6 aspirations.

## 5. Known failure modes

| Failure | Engine response |
|---|---|
| Hard gate fail (profile/fields/peers) | Method `INELIGIBLE` / `UNSUPPORTED`; no silent value |
| `WACC <= g + margin` | DCF path rejected with structured code |
| No eligible method for target | `INSUFFICIENT_METHOD_COVERAGE` — **not** a default FCFF |
| Incompatible method bases | Ensemble / blend refused |
| Uncalibrated mixture requested as production | Blocked; research `PRIOR_ONLY` only |
| Intrinsic copied to exit by default | Forbidden; exit requires market-pricing rule |
| Random time-series split in evaluation | `RandomSplitProhibitedError` |
| Inadequate calibration sample | `CALIBRATION_INSUFFICIENT` (not inferred success) |
| Critical data-quality in production | Run blocked (`EXIT_BLOCKED`) |

## 6. Data limitations

- Offline demos use **SYNTHETIC** CSV/Parquet only.
- Optional HiThink + Eastmoney NOTICE ingest exists for A-shares; restatement / NOTICE completeness is not guaranteed.
- Peer sets, corporate actions, and share counts must respect `as_of`; leakage suites enforce exclusions.
- Macro / risk-free adapters are not production-calibrated in this rc.

## 7. Calibration status

| Gate (SPEC §17.4) | Synthetic release status |
|---|---|
| `ENGINEERING_PASS` | Yes (phased tests + offline examples) |
| `DATA_QUALITY_PASS` | Yes on synthetic; real data depends on ingest |
| `CALIBRATION_PASS` | **No** — `CALIBRATION_INSUFFICIENT` |
| `ENSEMBLE_CALIBRATED` | **No** |
| `INVESTMENT_VALUE_NOT_ESTABLISHED` | **Yes (always on synthetic)** |
| `INVESTMENT_VALUE_SUPPORTED` | **Never** without separate predeclared OOS research protocol |

See [calibration_protocol.md](calibration_protocol.md) and `vms phase11` / `vms evaluate`.

## 8. Ethical / misuse notes

Do not present simulated distributions, attractive medians, or green unit tests as proof of profitability or alpha. Do not disable eligibility gates to force a single “fair value.” Do not ship CLI JSON with `INVESTMENT_VALUE_SUPPORTED` unless an audited OOS protocol has been executed and recorded outside this engineering package.
