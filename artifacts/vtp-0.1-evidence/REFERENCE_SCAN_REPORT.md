# Active Reference Scan Report

**Date**: 2026-11-10  
**Scan Scope**: tests/, artifacts/, excluding DEPRECATED_NOT_FOR_ACCEPTANCE/

---

## Simulation/Toy Artifact References

### `mutation_results.json` (simulation)

**Status**: Moved to `DEPRECATED_NOT_FOR_ACCEPTANCE/mutation_results_SIMULATED.json`

**Remaining References** (historical docs only):
- `artifacts/vtp-0.1-evidence/VTP-0.1_第三轮纠正报告.md` - historical
- `artifacts/vtp-0.1-evidence/VTP-0.1_第三轮实测报告.md` - historical
- `artifacts/vtp-0.1-evidence/gap6_mutation_honest_status.md` - historical
- `artifacts/vtp-0.1-evidence/ARTIFACT_MANIFEST_UPDATE.md` - cleanup record
- `artifacts/vtp-0.1-evidence/CLEANUP_MANIFEST.md` - cleanup record

**Active Scripts**: NONE (all moved to DEPRECATED)

**Verdict**: ✅ No active aggregators or scripts reference this file

---

### `SimplifiedRoutingEngine`

**Status**: Moved to `DEPRECATED_NOT_FOR_ACCEPTANCE/execute_ten_company_routing_SIMPLIFIED.py`

**Remaining References**:
- `tests/vtp_0_1/scripts/execute_production_routing_demo.py` - NEGATIVE reference (states "NOT SimplifiedRoutingEngine")

**Active Uses**: NONE

**Verdict**: ✅ No active code uses SimplifiedRoutingEngine

---

### `SimpleValuationModel`

**Status**: Still exists in `tests/vtp_0_1/suite_g/test_g_numerical_counterfactuals.py`

**Active Uses**: Suite G tests (NOT in scope for this round)

**Note**: Suite G toy model is out of scope; G-01至G-05 remain BLOCKED

**Verdict**: ⚠️ Exists but out of scope (G suite not in this round's scope)

---

## Current Authoritative Evidence

### Mutation Testing

**Active**: `artifacts/vtp-0.1-evidence/mutation_results_FINAL.json`  
**Executor**: `tests/vtp_0_1/scripts/execute_complete_production_mutations.py`

**No Conflicting Evidence**: All prior mutation results moved to DEPRECATED

---

## Verification Commands

```bash
# Check for active references to simulation files
grep -r "mutation_results\.json" tests/ artifacts/ 2>/dev/null | grep -v DEPRECATED

# Check for SimplifiedRoutingEngine usage
grep -r "SimplifiedRoutingEngine" tests/ --include="*.py" | grep -v DEPRECATED

# Verify no PASS claims from deprecated evidence
grep -r "mutation_results\.json.*PASS\|mutation_results_SIMULATED.*PASS" artifacts/ 2>/dev/null
```

---

## Conclusion

✅ **Clean**: No active aggregators, runners, or verdict files cite deprecated simulation evidence  
✅ **Isolated**: All simulation/toy artifacts in `DEPRECATED_NOT_FOR_ACCEPTANCE/`  
✅ **Single Authority**: `mutation_results_FINAL.json` is sole mutation evidence source

**Historical documents** retain references for audit trail but do not feed active acceptance decisions.
