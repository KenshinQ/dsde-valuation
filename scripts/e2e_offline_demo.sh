#!/usr/bin/env bash
# Offline end-to-end demo (SPEC §18 Phase 10 / §21 DoD).
# Path: validate → snapshot → estimate → simulate → project-paths → value →
# returns → sensitivity → evaluate (lightweight path counts for CI).
# Asserts ENGINEERING labels present + INVESTMENT_VALUE_NOT_ESTABLISHED.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x .venv/bin/python ]]; then PY=".venv/bin/python"; else PY="python3"; fi
if [[ -x .venv/bin/vms ]]; then VMS=".venv/bin/vms"; else VMS="$PY -m vms.cli.main"; fi

OUT="${1:-/tmp/vms_e2e_phase10}"
export E2E_OUT="$OUT"
SEED="${SEED:-42}"
TICKER="SYN000001.SZ"
ASOF="2025-06-30"
PATHS_SIM=40
PATHS_FP=30
PATHS_VAL=30
PATHS_RET=30
PATHS_SENS=20

rm -rf "$OUT"
mkdir -p "$OUT"

echo "==> [1/11] demo synthetic data"
$VMS demo --out "$OUT/demo" --seed "$SEED"
DATA="$OUT/demo/data"
test -d "$DATA"

echo "==> [2/11] validate-data"
$VMS validate-data --input "$DATA" --as-of "$ASOF" --ticker "$TICKER"

echo "==> [3/11] build-snapshot"
$VMS build-snapshot --input "$DATA" --ticker "$TICKER" --as-of "$ASOF" --out "$OUT/snap"

echo "==> [4/11] estimate"
$VMS estimate --input "$DATA" --ticker "$TICKER" --as-of "$ASOF" --out "$OUT/est" --seed "$SEED"

echo "==> [5/11] simulate (paths=$PATHS_SIM)"
$VMS simulate --input "$DATA" --ticker "$TICKER" --as-of "$ASOF" --out "$OUT/sim" \
  --paths "$PATHS_SIM" --years 3 --seed "$SEED"

echo "==> [6/11] project-paths (paths=$PATHS_FP)"
$VMS project-paths --input "$DATA" --ticker "$TICKER" --as-of "$ASOF" --out "$OUT/fp" \
  --paths "$PATHS_FP" --years 3 --seed "$SEED"

echo "==> [7/11] value (paths=$PATHS_VAL)"
$VMS value --input "$DATA" --ticker "$TICKER" --as-of "$ASOF" --out "$OUT/val" \
  --paths "$PATHS_VAL" --years 3 --seed "$SEED"

echo "==> [8/11] returns (paths=$PATHS_RET)"
$VMS returns --input "$DATA" --ticker "$TICKER" --as-of "$ASOF" --out "$OUT/ret" \
  --paths "$PATHS_RET" --years 3 --horizons 1,3 --seed "$SEED"

echo "==> [9/11] sensitivity (paths=$PATHS_SENS)"
$VMS sensitivity --input "$DATA" --ticker "$TICKER" --as-of "$ASOF" --out "$OUT/sens" --paths "$PATHS_SENS" --years 3 --seed "$SEED"

echo "==> [10/11] evaluate (lightweight synthetic universe)"
$VMS evaluate --universe config/universe.synthetic.yaml --start 2018-01-01 --end 2022-12-31 \
  --out "$OUT/eval"

echo "==> [11/11] assert labels + schema + INVESTMENT_VALUE_NOT_ESTABLISHED"
"$PY" - <<'PY'
import json, os, sys
from pathlib import Path

out = Path(os.environ["E2E_OUT"])
required = ["demo", "snap", "est", "sim", "fp", "val", "ret", "sens", "eval"]
missing = [n for n in required if not (out / n).exists()]
if missing:
    raise SystemExit(f"missing run-bundle parts: {missing}")

ret_sum = out / "ret" / "return_distribution_summary.json"
assert ret_sum.is_file(), ret_sum
ret = json.loads(ret_sum.read_text())
assert str(ret.get("schema_version", "")).startswith("vms-0.2"), ret.get("schema_version")

lab_path = out / "eval" / "evaluation_report.json"
assert lab_path.is_file(), lab_path
rep = json.loads(lab_path.read_text())
labels = rep["labels"]
assert labels["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
assert "ENGINEERING_PASS" in labels
assert "DATA_QUALITY_PASS" in labels
assert rep.get("schema_version", "").startswith("vms-0.2")

# Adapter import must work with DSDE absent
from vms.adapters.dsde import consumer_view_from_result, dsde_availability
assert dsde_availability()["dsde_present"] is False
assert dsde_availability()["required_for_core"] is False

print(json.dumps({
    "e2e": "PASS",
    "out": str(out),
    "schema_version_returns": ret["schema_version"],
    "schema_version_eval": rep.get("schema_version"),
    "ENGINEERING_PASS": labels["ENGINEERING_PASS"],
    "DATA_QUALITY_PASS": labels["DATA_QUALITY_PASS"],
    "investment_value": labels["investment_value"],
    "dsde_required": False,
}, indent=2, sort_keys=True))
PY

echo "E2E offline demo PASS → $OUT"
