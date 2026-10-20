#!/usr/bin/env bash
# Mutation check for the leakage suite: inject a known leak and require tests/leakage to FAIL for each.
# Each mutation is FILE<TAB>OLD<TAB>NEW[<TAB>OLD2<TAB>NEW2...] (literal replacements, all must apply). Files are restored afterwards.
# Usage: scripts/leakage_mutation_check.sh
set -u
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
TD=$(mktemp -d)
FILES="src/vms/pit/snapshot.py src/vms/drivers/walk_forward.py src/vms/pipeline.py"
for f in $FILES; do mkdir -p "$TD/$(dirname "$f")"; cp "$f" "$TD/$f"; done
restore() { for f in $FILES; do cp "$TD/$f" "$f"; done; }
trap 'restore; rm -rf "$TD"' EXIT
D='__import__("datetime").timedelta'
fail=0
while IFS=$'\t' read -r file rest; do
  [ -z "$file" ] && continue
  restore
  if ! $PY - "$file" "$rest" <<'PYEOF'
import sys
f, parts = sys.argv[1], sys.argv[2].split("\t")
s = open(f, encoding="utf-8").read()
for old, new in zip(parts[::2], parts[1::2]):
    if old not in s:
        sys.exit(1)
    s = s.replace(old, new)
open(f, "w", encoding="utf-8").write(s)
PYEOF
  then echo "NOT APPLIED: $file: ${rest%%$'\t'*}"; fail=1; continue; fi
  if $PY -m pytest tests/leakage -q -x -p no:cacheprovider >/dev/null 2>&1; then
    echo "SURVIVED (leak not detected): $file: ${rest%%$'\t'*}"; fail=1
  else
    echo "KILLED: $file: ${rest%%$'\t'*}"
  fi
done <<EOF2
src/vms/pit/snapshot.py	o.published_at <= as_of]	o.published_at <= as_of + $D(days=30)]
src/vms/pit/snapshot.py	o.timestamp <= as_of]	o.timestamp <= as_of + $D(days=30)]
src/vms/pit/snapshot.py	e.announced_at <= as_of]	e.announced_at <= as_of + $D(days=30)]
src/vms/pit/snapshot.py	if e.ex_date > d:	if e.ex_date > d or True:
src/vms/drivers/walk_forward.py	so, _, _ = build_snapshot(instrument_id=instrument_id, as_of=t,	so, _, _ = build_snapshot(instrument_id=instrument_id, as_of=t + $D(days=400),	assert all(f.published_at <= t for f in so.financials), "walk-forward origin saw post-origin data"	pass	if len(ho.years) < wf.min_train_years or max(ho.years, default=0) > y:	if len(ho.years) < wf.min_train_years:	if any(o.year > y for o in obs):	if False:
src/vms/pipeline.py	regimes = infer_regimes(snap.financials,	regimes = infer_regimes(__import__("vms.pit.snapshot", fromlist=["b"]).build_snapshot(instrument_id=instrument_id, as_of=snap.as_of + $D(days=400), financial=load.financial, market=[], corporate_actions=[], sources=load.sources)[0].financials,
EOF2
exit $fail
