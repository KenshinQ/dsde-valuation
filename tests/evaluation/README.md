Walk-forward evaluation tests: see `tests/unit/test_evaluation.py`,
`tests/unit/test_phase11_acceptance.py`, `tests/leakage/test_eval_weight_freeze.py`,
and `tests/integration/test_cli_phase11.py` (VMS-0.2 Phase 11 / SPEC §17).

Official VTP-0.1 E-01 routing truth table (production `vms.router.route_methods`,
10×12×4): `tests/evaluation/test_e01_production_routing_matrix.py`. Those tests
fail-closed: the official criterion is not PASS while mismatches, undeclared
expected cells, non-binary YAML statuses, a missing 12th method, or a
structurally unsupported TOTAL_RETURN target remain.
