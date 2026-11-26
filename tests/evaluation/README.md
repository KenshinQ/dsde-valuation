Walk-forward evaluation tests: see `tests/unit/test_evaluation.py`,
`tests/unit/test_phase11_acceptance.py`, `tests/leakage/test_eval_weight_freeze.py`,
`tests/integration/test_cli_phase11.py` (VMS-0.2 Phase 11 / SPEC §17), and
`tests/evaluation/test_suite_j_official_close_criteria.py` (official VTP-0.1
Suite J close bar: historical walk-forward, not distribution unit tests).

Those official-criteria tests fail-closed: a lean real-data slice with
`n_unbiased_pit_complete == 0` or `CALIBRATION_INSUFFICIENT` is not J-01..J-05 PASS.
