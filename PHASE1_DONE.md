# Phase 1 — completion report (VMS-0.2 §20 / §24)

Date: 2026-10-21 (Asia/Shanghai). Repo: local git only, no remote. Branch: `master`.
Prior freeze tag: `vms-0.1`. Spec: `SPEC.md` (VMS-0.2). Prior contracts: [PHASE0_DONE.md](PHASE0_DONE.md).

Status: **all Phase 1 acceptance criteria pass** for the PIT data layer and accounting gates.
Label: `ENGINEERING_PASS` for Phase 1 only; `INVESTMENT_VALUE_NOT_ESTABLISHED`.
This is **not** a valuation and does **not** claim investment value. Phases 2+ (profile/router/methods) are **not** claimed done.

## Changed / added files (VMS-0.2 Phase 1)
```
src/vms/__init__.py                    SCHEMA_VERSION=vms-0.2.phase1, IMPLEMENTED_PHASE=PHASE_1
src/vms/schemas/observations.py        QualityStatus §6.1 uppercase aliases; optional
                                       source_document_id / derivation_rule_id; NEW PeerObservation
src/vms/schemas/__init__.py            export PeerObservation
src/vms/data/io.py                     peer_observations.{csv,parquet} load/write; LoadResult.peers
src/vms/pit/snapshot.py                PIT-SNAPSHOT-3 + peers; peer_known_at(); excluded_post_as_of.peers
src/vms/quality/issues.py              PEER_* issue codes under PEER_CONTAMINATION
src/vms/quality/checks.py              PEER_CONTAMINATION in CHECK_CATALOGUE (RUN)
src/vms/quality/report.py              pass load.peers into build_snapshot
config/default.yaml (+ sidecars)       configuration/registry/router/profiles → *.phase1
docs/data_contracts.md                 PEER_CONTAMINATION + peer PIT rules
scripts/leakage_mutation_check.sh      peer published_at filter mutation (400d)
tests/conftest.py                      make_load(..., peers=())
tests/unit/test_peers_phase1.py        NEW (schema aliases, PeerObservation, IO, snapshot filter)
tests/leakage/test_peer_leakage.py     NEW (membership, survivorship, metrics, invariant)
tests/*/…                              schema_version assertions → vms-0.2.phase1
PHASE1_DONE.md                         this report (replaces VMS-0.1 Phase 1 narrative)
README.md / examples/…                 schema contract pointer
```

Migrated (unchanged behaviour, still green): VMS-0.1 PIT/quality suite under
`src/vms/{pit,quality,data}` — post-as_of exclusion, restatement vintages, CN_CUMULATIVE_YTD
conversion, unit/currency and balance-sheet gates, production BLOCK, exploratory override.

Empty `vms.methods` / `vms.router` / `vms.profiles` packages were **not** created (SPEC §22/§24).

## Commands executed
| Environment | Command | Result |
|---|---|---|
| Repo `.venv` (Python 3.13) | `python -m pytest` | **522 passed** (Phase 0 was 509; +8 unit peers +5 peer leakage) |
| Offline contracts demo | `vms phase0 --out /tmp/vms_phase0_p1 --seed 42 --paths 50` | exit 0; `schema_version=vms-0.2.phase1`, `implemented_phase=PHASE_1`, status still `PHASE0_CONTRACTS_BASELINE_NOT_A_VALUATION` |
| Mutation | `scripts/leakage_mutation_check.sh` | **7/7 injected leaks KILLED** (financial published_at, market timestamp, CA announced_at, **peer published_at**, ex_date adjust, walk-forward, pipeline regimes) |

## Acceptance criterion → evidence

| # | Criterion (SPEC §20 Phase 1) | Evidence |
|---|---|---|
| 1 | Observations published after `as_of` are excluded | `build_snapshot` filters financials by `published_at`, prices by `timestamp`, actions by `announced_at`, peers by `peer_known_at`. Tests: `tests/leakage/test_leakage.py::test_every_snapshot_input_known_at_as_of`, `test_future_publication_excluded_late_annual_report`, `test_date_only_as_of_excludes_evening_publication_same_day`, `tests/unit/test_peers_phase1.py::test_snapshot_excludes_future_peers`. |
| 2 | Later revisions do not change earlier snapshots | `test_snapshot_invariant_to_information_after_as_of`, `test_future_restatement_excluded`, `test_injected_future_restatement_of_old_period_does_not_change_old_snapshot`, `test_peer_snapshot_invariant_to_information_after_as_of`, `test_survivors_only_reconstitution_does_not_drop_historical_peer`. |
| 3 | Cumulative quarterly flows converted only under identified reporting convention | `tests/unit/test_snapshot.py` CN_CUMULATIVE_YTD → standalone; `CUMULATIVE_CONVENTION_UNKNOWN` when undeclared; stocks never converted (`test_stocks_never_converted` and related). Convention id: `ReportingConvention.CN_CUMULATIVE_YTD` in `sources.yaml`. |
| 4 | Unit/currency and balance-sheet/accounting discrepancies are surfaced | `UNIT_CURRENCY` / `BALANCE_SHEET_IDENTITY` checks in `vms.quality.checks`; tests in `tests/unit/test_quality.py` (currency not CNY CRITICAL; balance-sheet fail WARNING; sign violations CRITICAL). |
| 5 | Critical errors block production-mode calculation | `vms.quality.report.gate` + CLI exit 3; `test_critical_blocks`, `test_build_snapshot_blocked_production_exit_3_no_snapshot`; exploratory requires `--override-reason` (`test_exploratory_override_recorded`). |
| 6 | Leakage tests cover financials, peer data, prices and corporate actions | Financials/prices/CA: `tests/leakage/test_leakage.py` (12). Peers: `tests/leakage/test_peer_leakage.py` (5) — future membership publication, future membership_start, survivors-only reconstitution, future peer metric/price, full invariant. Mutation evidence above. |

## Example artifact summary
```text
vms phase0 --out /tmp/vms_phase0_p1 --seed 42 --paths 50
→ status=PHASE0_CONTRACTS_BASELINE_NOT_A_VALUATION
→ schema_version=vms-0.2.phase1  implemented_phase=PHASE_1
→ investment_value=INVESTMENT_VALUE_NOT_ESTABLISHED
```

PIT peer sample is exercised in unit/leakage tests (not in the Phase 0 contracts demo).

## Known gaps (honest)
- No profile classifier, method registry population beyond Phase 0 placeholders, FCFF rewrite, router, ensemble, or market-pricing engine (Phases 2–9).
- `PeerObservation` is the PIT **data** contract only; relative-valuation peer universes / multiples remain Phase 5.
- Observation `QualityStatus` still **serialises lowercase** (`observed`, …) for CSV compatibility; SPEC §6.1 uppercase is accepted at parse time. `ObservationQualityStatus` keeps uppercase spellings.
- Optional `source_document_id` / `derivation_rule_id` are schema-ready but not required on legacy rows.
- No FX: non-CNY amounts still BLOCK (including peer metrics).
- Vendor `adjusted_close` still excluded from snapshots; audit-only.
- `PIT_INCOMPLETE` does not block production; it marks data unfit for unbiased-history claims.
- Real A-share providers remain for regression; Phase 1 acceptance is on synthetic/offline evidence.
- Engineering pass ≠ investment alpha.

## Failed criteria
None. No criterion was weakened.
