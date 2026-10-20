# VMS-0.1 Model Card

| Field | Value |
|---|---|
| Package | `dsde-valuation` / `vms` |
| Version | `0.1.0` |
| Schema contract | `vms-0.1.0` (OUTPUT-CONTRACT-v1) |
| Spec | SPEC.md §1–§21 |
| Status | Engineering release on **synthetic** data only |

## 1. Purpose

VMS-0.1 is a **standalone** China A-share valuation and conditional-return engine. Given a PIT
information set and config, it produces:

- regime-conditional driver distributions;
- correlated Monte Carlo paths and path-wise financial statements;
- FCFF DCF (+ exit-multiple cross-check) value distributions;
- entry-price-conditioned multi-horizon return mixtures (DIVIDEND-NO-REINVEST);
- sensitivity / uncertainty attribution;
- chronological walk-forward evaluation labels.

It is **not** a trading system, Kelly sizer, or portfolio optimizer. Optional delivery of
distributions to a DSDE decision layer is behind `vms.adapters.dsde` and does **not** require
DSDE to be installed for core valuation.

## 2. Supported profiles

| Profile id | Status | Notes |
|---|---|---|
| `operating_company` | **Supported** | Generic non-financial FCFF / EV bridge. Config-driven driver profile. |
| Banks / insurance / brokerages | **Unsupported** | Listed in config `sector_profiles.unsupported` → `UNSUPPORTED_PROFILE` (raw metrics only; no projection/DCF). |
| Conglomerates / holding cos without operating FCFF | **Unsupported** | No dedicated profile; treat as unsupported unless mapped explicitly. |
| Cross-listed / non-CNY primary statements | **Blocked** | `CURRENCY_NOT_CNY` critical; FX conversion not implemented. |

See also `config/default.yaml` `sector_profiles` and `docs/architecture.md`.

## 3. Unsupported / out of scope (VMS-0.1)

- Real provider adapters (HiThink / Wind / etc.) — **future work**; offline CSV/Parquet + SYNTHETIC only.
- HMM market regimes (`regimes.model: hmm`) — interface only; exit code 2 (REGIME-HMM-DEFERRED-v1).
- Portfolio construction, position sizing, execution, live streaming.
- Claiming `INVESTMENT_VALUE_SUPPORTED` without predeclared leakage-safe OOS evidence (never on SYNTHETIC).
- Legacy PIT/FTD/DV1 / `dsde-engine` imports (forbidden; tested).
- Reinvested-dividend TSR; only DIVIDEND-NO-REINVEST pathwise cash + terminal equity value.
- Automatic FX conversion; non-CNY amounts are blocked.

## 4. Key assumptions (auditable)

Versioned register: `docs/assumptions.md` / `vms.assumptions`. Highlights:

- ASOF-DATE-CLOSE-v1 — date-only `as_of` = 15:00 Asia/Shanghai.
- TV-GORDON-v1 / WACC from explicit config `valuation.risk_free_rate` (never invented).
- DIVIDEND-NO-REINVEST-v1 for holding-period returns.
- Chronological walk-forward only (random splits raise `RandomSplitProhibitedError`).
- MC percentile bands are **not** confidence intervals (SENS-MC-PERCENTILE-NOT-CI-v1).

## 5. Investment-value policy

**Default label: `INVESTMENT_VALUE_NOT_ESTABLISHED`.**

Engineering / data-quality / calibration labels are reported separately
(`ENGINEERING_PASS`, `DATA_QUALITY_PASS`, `CALIBRATION_*`). Passing engineering tests or
synthetic walk-forward **never** implies alpha or investability (EVAL-INVESTMENT-LABEL-v1,
SPEC §15.3 / §21).

## 6. Calibration status

| Domain | Status |
|---|---|
| Offline SYNTHETIC panel | Metrics produced; label **INCONCLUSIVE / SYNTHETIC_ONLY** |
| Real A-share OOS | **Not established** in VMS-0.1 (no HiThink adapter; no predeclared OOS protocol executed on live data) |

## 7. Known limitations

1. Synthetic annual panel ≠ full quarterly richness of live filings.
2. Parameter uncertainty via bootstrap + regime Dirichlet; not a full Bayesian hierarchical model.
3. Copula is Gaussian over shrunk residual correlations — tail dependence understated.
4. Terminal value and WACC dominate sensitivity; process vs param split is diagnostic, not a CI.
5. Evaluation intrinsic-stability vs later-origin VPS is reserved / not fully backfilled.
6. Provider-specific restatement / dual-share / ST/*ST nuances are not modeled beyond SYNTHETIC fixtures.

## 8. Intended users

Quant researchers integrating conditional value/return distributions into a separate decision
layer (e.g. optional DSDE). Not for retail investment advice.

## 9. Contact / provenance

Local git only in the development box; no remote publish implied by this card. Schema stamps
every public artifact with `schema_version: vms-0.1.0`.
