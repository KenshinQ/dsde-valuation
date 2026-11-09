# VTP-0.1 Evidence Cleanup Manifest

**Date**: 2026-11-09  
**Action**: Remove simulation/toy artifacts; consolidate to single authoritative evidence

---

## Moved to DEPRECATED_NOT_FOR_ACCEPTANCE/

| Original Path | New Location | Reason |
|---------------|--------------|--------|
| `mutation_results.json` | `DEPRECATED_NOT_FOR_ACCEPTANCE/mutation_results_SIMULATED.json` | Contains `simulation_note`; toy assumptions |
| `tests/vtp_0_1/scripts/execute_mutations.py` | `DEPRECATED_NOT_FOR_ACCEPTANCE/execute_mutations_SIMULATED.py` | Simulated mutation runner (no real patches) |
| `tests/vtp_0_1/scripts/execute_ten_company_routing.py` | `DEPRECATED_NOT_FOR_ACCEPTANCE/execute_ten_company_routing_SIMPLIFIED.py` | Used `SimplifiedRoutingEngine` (62 mismatches) |

## Superseded Files

| File | Status | Replaced By |
|------|--------|-------------|
| `mutation_results_PRODUCTION.json` | Superseded | `mutation_results_COMPLETE.json` |
| `mutation_results_REAL_TOY_DEPRECATED.json` | Deprecated | N/A (toy demo) |
| `execute_real_mutations_TOY_DEPRECATED.py` | Deprecated | N/A (toy demo) |
| `execute_production_mutations.py` | Superseded | `execute_all_production_mutations.py` |

---

## Current Authoritative Evidence

### Suite I Mutation Testing

**File**: `mutation_results_COMPLETE.json`  
**Executor**: `tests/vtp_0_1/scripts/execute_all_production_mutations.py`

**Summary**:
- Total planned: 6
- Executed: 3 (I-M01, I-M02, I-M05)
- Killed: 2 (I-M01, I-M05)
- Survived: 1 (I-M02)
- Not executed: 3 (I-M03, I-M04, I-M06)
- Mutation score: 66.7% (2/3 executed)

**Honest Reporting**:
- I-M02 SURVIVED: Detector test `test_property_ineligible_method_contributes_no_values` insufficient
- No toy functions, no temp files, no simulation_note
- Direct src/vms/ production file modification only

---

## Active Evidence Inventory

| Evidence Type | File | Status |
|---------------|------|--------|
| **Mutation Testing** | `mutation_results_COMPLETE.json` | ✅ AUTHORITATIVE |
| **A-02 JUnit** | `junit_a02_fresh.xml` | ✅ VALID (2026-11-09) |
| **Production Routing** | `production_routing_demo.json` | ✅ VALID (partial, 1 path) |
| **Fail-Closed Verdicts** | `verdicts_final_failclosed.json` | ✅ AUTHORITATIVE |
| **Gap Status** | `HONEST_GAP_STATUS_FINAL.md` | ✅ VALID |

---

## References Scan

Checked for stale references to:
- `mutation_results.json` (original simulation)
- `execute_mutations.py` (simulation runner)
- `SimplifiedRoutingEngine`
- `SimpleValuationModel`
- `simulation_note` field

**Action**: All active documents and aggregators updated to reference only authoritative evidence.

---

## Verification Commands

```bash
# Verify DEPRECATED directory
ls -la artifacts/vtp-0.1-evidence/DEPRECATED_NOT_FOR_ACCEPTANCE/

# Verify no active references to deprecated files
grep -r "mutation_results\.json" artifacts/vtp-0.1-evidence/*.json 2>/dev/null | grep -v DEPRECATED | grep -v COMPLETE

# Verify authoritative evidence exists
ls -lh artifacts/vtp-0.1-evidence/mutation_results_COMPLETE.json
```

---

## IMPORTANT: Do Not Cite Deprecated Evidence

Files in `DEPRECATED_NOT_FOR_ACCEPTANCE/` **MUST NOT** be cited for acceptance criteria. They are preserved for historical reference only.

Only `mutation_results_COMPLETE.json` and its executor `execute_all_production_mutations.py` count toward Suite I acceptance.
