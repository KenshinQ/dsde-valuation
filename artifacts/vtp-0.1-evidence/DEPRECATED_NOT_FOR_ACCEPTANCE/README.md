# DEPRECATED - NOT FOR ACCEPTANCE

**WARNING**: This directory contains deprecated simulation/toy implementations that **DO NOT** count toward VTP-0.1 acceptance.

## Contents

### Simulated/Toy Implementations (NOT VALID EVIDENCE)

1. **mutation_results_SIMULATED.json** (原 `mutation_results.json`)
   - Contains `simulation_note` field
   - Used toy assumptions instead of real source patches
   - Status: DEPRECATED - Do not cite for acceptance

2. **execute_mutations_SIMULATED.py** (原 `execute_mutations.py`)
   - Simulated mutation testing runner
   - Did not patch real source files
   - Status: DEPRECATED - Do not use

3. **execute_ten_company_routing_SIMPLIFIED.py** (原 `execute_ten_company_routing.py`)
   - Used `SimplifiedRoutingEngine` instead of production `vms.router.route_methods`
   - Produced 62 mismatches and 344 unknown decisions
   - Status: DEPRECATED - Do not cite

## Valid Evidence Location

Real production evidence is located in:
- `../mutation_results_PRODUCTION.json` - Real source file mutations (I-M01, I-M05 KILLED)
- `../production_routing_demo.json` - Real production routing API call
- `../../tests/vtp_0_1/scripts/execute_production_mutations.py` - Real mutation executor

## History

These files were used in early rounds before the independent audit rejection of simulation-based evidence. They are preserved for historical reference only and **must not** be cited in acceptance criteria evaluation.

**Date deprecated**: 2026-11-09  
**Reason**: Simulation/toy implementations rejected by independent audit
