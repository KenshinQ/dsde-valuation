#!/usr/bin/env bash
# Run all five VMS-0.2 Phase 12 offline synthetic examples (SPEC §19 / §20).
# Engineering smoke only — INVESTMENT_VALUE_NOT_ESTABLISHED. No alpha claim.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -x .venv/bin/vms ]]; then VMS=".venv/bin/vms"; else VMS="python -m vms.cli.main"; fi
OUT="${1:-/tmp/vms_offline_examples}"
SEED="${SEED:-42}"
PATHS="${PATHS:-12}"
YEARS="${YEARS:-2}"
rm -rf "$OUT"
mkdir -p "$OUT"
echo "==> phase12 release → $OUT (paths=$PATHS years=$YEARS seed=$SEED)"
$VMS phase12 --out "$OUT" --seed "$SEED" --paths "$PATHS" --years "$YEARS"
echo "==> validate each pattern"
for pat in mature_operating growth_negative_fcf financial_institution cyclical holding; do
  subset=phase12
  if [[ "$pat" == "mature_operating" ]]; then subset=phase12_mature_full; fi
  $VMS validate-bundle --path "$OUT/$pat" --subset "$subset" >/dev/null
  echo "  OK $pat ($subset)"
done
echo "==> done (NOT investment advice)"
