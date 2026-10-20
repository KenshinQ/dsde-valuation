#!/usr/bin/env bash
# Mutation check for the leakage suite: inject a known leak into the PIT filters and require
# tests/leakage to FAIL for each. Restores the file afterwards. Usage: scripts/leakage_mutation_check.sh
set -u
cd "$(dirname "$0")/.."
F=src/vms/pit/snapshot.py
BAK=$(mktemp)
cp "$F" "$BAK"
trap 'cp "$BAK" "$F"; rm -f "$BAK"' EXIT
PY=${PY:-.venv/bin/python}
fail=0
for mut in \
  's/o.published_at <= as_of\]/o.published_at <= as_of + __import__("datetime").timedelta(days=30)]/' \
  's/o.timestamp <= as_of\]/o.timestamp <= as_of + __import__("datetime").timedelta(days=30)]/' \
  's/e.announced_at <= as_of\]/e.announced_at <= as_of + __import__("datetime").timedelta(days=30)]/' \
  's/if e.ex_date > d:/if e.ex_date > d or True:/'; do
  cp "$BAK" "$F"; sed -i "$mut" "$F"
  if cmp -s "$F" "$BAK"; then echo "NOT APPLIED: $mut"; fail=1; continue; fi
  if $PY -m pytest tests/leakage -q -x -p no:cacheprovider >/dev/null 2>&1; then
    echo "SURVIVED (leak not detected): $mut"; fail=1
  else
    echo "KILLED: $mut"
  fi
done
exit $fail
