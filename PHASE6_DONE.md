# Phase 6 — DCF & multiple cross-check: DONE

Also includes Phase 5 review decisions (central-path gate, path-ledger parquet, buyback last-close).

Not started: Phase 7 (entry-price return distributions).

## Decisions recorded
| ID | Decision |
|---|---|
| CENTRAL-PATH-GATE-v1 | Central path failure BLOCK in production (non-zero exit); exploratory + recorded override. Critical modeling failure. |
| PATH-LEDGER-PARQUET-v1 | Default write full path ledgers as parquet; JSON summary stays lean. |
| BUYBACK-PRICE-LAST-CLOSE-v1 | VMS-0.1 buybacks at last close; price paths belong to Phase 7. |
| WACC-RF-CONFIG-v1 | `valuation.risk_free_rate` MUST be supplied (labeled); never invent. Production PIT 10y CGB adapter later. |
| WACC-BETA-SHRINK-v1 | β = (n·β_raw + k·prior)/(n+k); synthetic may supply explicit beta / cost_of_equity with provenance. |
| WACC-CONSTRUCTION-v1 | WACC = we·ke + wd·kd·(1−tc); ke = rf+β·erp (or override). |
| TV-GORDON-v1 | TV = FCFF[n]·(1+g)/(WACC−g); reject WACC_G_MARGIN_FAIL (no silent repair); TV/EV warn. |
| EXIT-MULTIPLE-SEPARATE-v1 | Exit-multiple reported separately; composite only if versioned `composite_weights` (default null). |
| EV-EQUITY-BRIDGE-v1 | EV+cash−debt−leases−minority−other; components reported; negative equity preserved; diluted shares > 0. |

## Changed / new files
- `src/vms/valuation/{wacc,dcf,multiples,value}.py` — WACC, Gordon DCF, exit-multiple, path valuation
- `src/vms/equity_bridge/bridge.py` — EV→equity bridge
- `src/vms/statements/paths.py` — CentralPathError + production BLOCK; ledger parquet write
- `src/vms/pipeline.py` — `Phase6Run` / `run_valuation`; central-path mode/override
- `src/vms/engine.py` — `value_paths` / `value_from_load` / `run` through Phase 6
- `src/vms/cli/main.py` — `vms value`; `_write_phase6` (valuation_summary.json + path_valuations.parquet); demo Phase 6
- `src/vms/schemas/config.py` — ValuationConfig (RF required), TerminalValueConfig, ExitMultipleConfig
- `config/default.yaml` — valuation block (rf=0.025 labeled, erp=0.06, beta=1.0, composite_weights null)
- assumptions register + docs + CI (`vms value` step)
- Tests: `test_valuation.py` (8), `test_phase5_followups.py` (2), `test_cli_value.py` (1)

## Tests
- **429 passed** (~158 s box; clean clone + uv/py3.11 + requirements.lock: **429 passed** in 175 s; `vms value` exit 0, n_valid_dcf=50, artifacts valuation_summary.json + path_valuations.parquet + financial_path_ledgers.parquet).
- Leakage mutation: **6/6 KILLED**. Invariant mutation: **7/7 KILLED**.

## Acceptance evidence

1. **WACC construction (RF required; beta shrink; no silent invent).**
   - `test_wacc_hand_fixture`: ke = rf+β·erp; WACC = we·ke+wd·kd·(1−tc); assumptions include WACC-RF-CONFIG-v1.
   - `test_shrink_beta_formula`: (n·β_raw+k·prior)/(n+k).
   - Config forbids missing RF (Pydantic required field); provenance labels on all WACC inputs.

2. **Gordon TV with WACC>g margin; reject invalid paths (no silent repair).**
   - `test_dcf_hand_fixture_matches_present_value`: hand PV(FCFF)+PV(TV) within tolerance; FCFF typed with WACC only.
   - `test_wacc_g_margin_rejects_without_repair`: `invalid_reason=WACC_G_MARGIN_FAIL`, flag `NO_SILENT_DENOMINATOR_REPAIR`.
   - TV fraction reported; `TV_FRACTION_HIGH` / `TV_FRACTION_HIGH_PRESENT` when above threshold.

3. **Exit-multiple cross-check separate; robust peers/shrink; no auto-average.**
   - `test_exit_multiple_separate_and_shrink`: peer median + shrink; PEER_SCARCITY; default `composite_weights is None`.
   - Path valuation keeps DCF and exit-multiple separate (`composite_equity is None` unless weights set).

4. **EV→equity bridge; components; negative equity preserved; diluted shares.**
   - `test_bridge_hand_fixture_and_negative_equity_preserved`: 1000+50−200−30−20−10=790; VPS=7.9;
     negative equity kept with `NEGATIVE_EQUITY_PRESERVED`; `NONPOSITIVE_SHARES` rejects.

5. **Hand fixtures match within tolerance; path + CLI artifacts.**
   - Hand WACC/DCF/bridge tests above.
   - `test_path_valuation_end_to_end` / `test_engine_value_paths`: central VALID, n_valid_dcf, separate exit-multiple.
   - `vms value` → `valuation_summary.json` + `path_valuations.parquet` (+ `financial_path_ledgers.parquet`); schema `vms-0.1.phase6`.
   - Facade: `ValuationEngine.value_paths`.

6. **Phase 5 follow-ups implemented.**
   - `test_central_path_blocks_production` / parquet ledger tests in `test_phase5_followups.py`.

## Limitations
1. RF is config assumption (labeled), not a live PIT 10y CGB adapter.
2. Synthetic default `beta_n_eff=0` → shrink to prior unless n_eff/series provided; no live CSI300 beta fetch.
3. TV/EV fraction often high on short horizons (warned, not auto-fixed).
4. Buyback still last close (BUYBACK-PRICE-LAST-CLOSE-v1); price paths Phase 7.
5. Exit-multiple peers are explicit config/synthetic; no live peer universe adapter.
6. Suite ~2.6 min (path projection × N + valuation).

## New questions
1. Production RF adapter: source/vendor for PIT 10y CGB and refresh cadence?
2. When beta series is missing in production, BLOCK vs shrink-to-1 with flag?
3. Default horizon / terminal growth bounds for A-share cyclicals to keep TV/EV below warning threshold?
