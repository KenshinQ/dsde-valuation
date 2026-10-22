# R2c→R2d — Deposit-taking FI P/B-ROE + Track B own-hist P/B exit: DONE

Date: 2026-10-22 (Asia/Shanghai). Branch: `feat/r2-bank-rim-cd` (from `02fae3b` / R2a+b merge).
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
Prior: `PHASE_R2_BANK_RIM_DONE.md`. Pace: **r2cd-default** (user widget).

Status: **R2c + R2d acceptance criteria pass** (machinery + unit AC; smoke documents honest UNAVAILABLE/PEER_SCARCITY where data thin).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED`. Engineering smoke ≠ investment advice.
Does **not** claim OOS calibration, ensemble, gate lift, or 非银金融 support.

## Design
- **R2c**: value-rim sidecar `rim_pb_roe.json`. Peer field `pb_common` = raw_close / (common_equity/shares). PIT via `build_peer_set` / `peer_known_at`. Same SW L1 deposit-taking FI filter when label known. `n < peer_min_count` (incl. empty) → `INELIGIBLE` / `PEER_SCARCITY` (no silent fill). Subject P/B + ROE always reported beside RIM. Shared book math note — **not** independent intrinsic evidence. No ensemble; legacy `vms value` gate untouched.
- **R2d**: RIM P2 book paths → `FinancialPathBundle` (common equity placed in `total_equity@year` with flag `COMMON_EQUITY_IN_PB_DENOM_FIELD`) → `generate_exit_prices(metric_id=pb)` with **own-hist common P/B median as family center** (forbids default pb=2.0) → `build_return_distributions_from_exit_prices`. Hist points < 12 → channel `UNAVAILABLE` (explicit). Never copies intrinsic VPS to exit (`MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1`).
- **Assumptions**: `RIM-PB-ROE-PEER-v1`, `RIM-EXIT-OWN-PB-HIST-v1`.

## Changed / added files (high level)
```
src/vms/methods/rim/hist_pb.py          NEW own-hist common P/B
src/vms/methods/rim/pb_roe.py           NEW R2c relative sidecar
src/vms/methods/rim/book_paths.py       NEW RIM→FinancialPathBundle
src/vms/methods/rim/track_b_exit.py     NEW R2d orchestration
src/vms/reporting/value_rim_bundle.py   wire sidecars + summary/RUN_REPORT
src/vms/assumptions.py / docs/assumptions.md
tests/unit/methods/test_rim_r2cd_*.py
PHASE_R2CD_BANK_RIM_DONE.md
```

## Commands / tests
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` | `python -m pytest` | **715 passed**, 2 skipped |
| Smoke | `vms value-rim ... --out /tmp/vms_000001_rim_r2cd` | R2a/b numbers retained; R2c PEER_SCARCITY; R2d UNAVAILABLE (hist n&lt;12) |

## Acceptance → evidence

### R2c
| # | Criterion | Evidence |
|---|---|---|
| 1 | Peer P/B = raw close / common BPS | `pb_roe.py` + unit `test_peer_relative_vps_with_synthetic_peers` |
| 2 | PIT peers; scarcity → INELIGIBLE | `test_peer_scarcity_when_no_peers`, `test_pit_excludes_future_peer_metric` |
| 3 | Subject P/B-ROE beside RIM; shared-book note | summary `pb_roe` + `SHARED_BOOK_MATH_NOT_INDEPENDENT_EVIDENCE` |
| 4 | Sidecar not ensemble | `ensemble: null`; artifacts `rim_pb_roe.json` |
| 5 | Legacy gate intact | no change to `industry.unsupported` / `vms value` |

### R2d
| # | Criterion | Evidence |
|---|---|---|
| 1 | RIM book paths → ExitPriceBundle → Track B | `track_b_exit.py` + `test_track_b_valid_with_ge_12_hist_no_intrinsic_copy` |
| 2 | Exit multiple from own hist common P/B; not default 2.0 | `pb_center_used ≈ hist.median`; `abs(center-2)>0.5` in unit |
| 3 | hist &lt; 12 → UNAVAILABLE | `test_hist_pb_unavailable_when_lt_12`, `test_track_b_unavailable_when_hist_lt_12`; 000001 smoke |
| 4 | No silent intrinsic exit | `default_forbids_intrinsic_copy`; flags `NO_SILENT_INTRINSIC_EXIT` |
| 5 | Assumptions registered | `RIM-PB-ROE-PEER-v1`, `RIM-EXIT-OWN-PB-HIST-v1` |

## Smoke notes (000001.SZ @ 2025-06-30, Asia/Shanghai)
Engineering only — **not** investment value. Out: `/tmp/vms_000001_rim_r2cd/`.

| metric | value |
|---|---|
| common_equity_0 | **424,894,000,000** |
| last_fy_dps | **0.608** |
| P2 VPS ke=0.08 p50 | **43.515** (unchanged vs R2b) |
| pb_roe.status | **INELIGIBLE** / PEER_SCARCITY (no peer_observations) |
| pb_roe.subject_pb | reported (raw_close / common BPS) |
| track_b.status | **UNAVAILABLE** (N_HIST_PB=9&lt;12) |
| track_b.pb_center_used | null (channel not opened; default 2.0 not applied) |
| investment_value | INVESTMENT_VALUE_NOT_ESTABLISHED |
| artifacts | rim_pb_roe.json, rim_track_b.json |

Local OEI history yields **9** FY common-P/B points under PIT → Track B **UNAVAILABLE** (honest). No peer CSV → R2c **PEER_SCARCITY** while subject P/B/ROE still reported. R2a/b numbers unchanged.

## Known gaps (honest)
- No live bank peer universe provider yet; peers must be supplied via `peer_observations` input (or remain PEER_SCARCITY).
- Own-hist common P/B limited by OEI coverage (annual); no silent OEI carry-forward.
- SCHEMA_VERSION remains `vms-0.2.phase12`.
- Walk-forward calibration / ensemble / gate lift / 非银金融 out of scope.

## Label
`INVESTMENT_VALUE_NOT_ESTABLISHED` — engineering smoke ≠ investment advice.
