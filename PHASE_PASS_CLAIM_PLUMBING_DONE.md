# PASS-claim plumbing: DONE

Date: 2026-11-03 (Asia/Shanghai). Branch: `feat/pass-claim-plumbing`.
Base: stacked on `feat/mature-lean-wf-calibrate` @ `46a756a` (PR #28) because
`calibrate-mature` wiring is required by SPEC; independent of master alone would
omit that CLI.
Remote: `origin` → https://github.com/KenshinQ/dsde-valuation
SPEC: `/workspace/PASS_CLAIM_PLUMBING_SPEC.md` (slice C).

Status: **acceptance criteria pass** (unit ≥3; default path INSUFFICIENT;
illegal artifact fail-closed; valid+n=0 still INSUFFICIENT).
Label: `INVESTMENT_VALUE_NOT_ESTABLISHED` unchanged.
**Plumbing ≠ evidence** — this PR does **not** flip any real run to
`CALIBRATION_PASS`, does not invent OOS, does not lower MIN, does not claim
`ENSEMBLE_CALIBRATED` / `INVESTMENT_VALUE_SUPPORTED`, and does **not** bump
SCHEMA/package (`vms-0.2.phase12` / `0.2.0rc1`).

## Design
- Module `vms.evaluation.pass_claim`: validate / resolve / gate.
- `assign_labels(..., pass_claim_authorized=False)` fail-closed: True candidate
  without auth → `CALIBRATION_INSUFFICIENT`.
- Wired: `run_rim_calibration`, `run_evaluation`, `calibrate_rim_bundle`,
  `calibrate_mature_bundle`, CLI `--pass-claim-artifact`.
- Assumption: `EVAL-CALIBRATION-PASS-CLAIM-PROTOCOL-v1`.

## Changed / added files
```
src/vms/evaluation/pass_claim.py                 NEW
src/vms/evaluation/labels.py                     pass_claim_authorized gate
src/vms/evaluation/rim_run.py                    resolve + gate
src/vms/evaluation/run.py                        resolve + gate
src/vms/reporting/calibrate_rim_bundle.py        artifact + decision artifact
src/vms/reporting/calibrate_mature_bundle.py     artifact + decision artifact
src/vms/cli/main.py                              --pass-claim-artifact
src/vms/assumptions.py / docs/assumptions.md     PROTOCOL-v1
docs/calibration_protocol.md                     PASS-claim section
tests/unit/test_pass_claim_plumbing.py           AC4 ≥3
PHASE_PASS_CLAIM_PLUMBING_DONE.md
```

## AC map
1. Default no artifact → INSUFFICIENT (unchanged forced paths).
2. Illegal/synthetic/incomplete → `PassClaimArtifactError` / bundle InputError.
3. Valid + n=0 → `INSUFFICIENT_N_UNBIASED`, still INSUFFICIENT.
4. Unit tests in `tests/unit/test_pass_claim_plumbing.py`.
5. Docs + this DONE.
6. PR body states: no PASS empirics from this knife.
