#!/usr/bin/env bash
# Mutation check for the §9.2 invariant checker: inject typical modelling bugs into the projection
# engine and require the projection to be REJECTED (validity tests FAIL). The checker is independent
# of the projection code, so it must catch these without knowing the bug. Restores the file afterwards.
set -u
cd "$(dirname "$0")/.."
F=src/vms/statements/projection.py
BAK=$(mktemp)
cp "$F" "$BAK"
trap 'cp "$BAK" "$F"; rm -f "$BAK"' EXIT
PY=${PY:-.venv/bin/python}
T="tests/unit/test_projection.py::test_valid_and_fully_traced_for_every_policy"
fail=0
for mut in \
  's/ni + da - dnwc, "net_income/ni + da, "net_income/' \
  's/nopat + da - capex - dnwc - acq,/nopat + da - dnwc - acq,/' \
  's/cfo - capex - acq + nb, "CFO/cfo - capex + nb, "CFO/' \
  's/+ ni - dist + iss,/+ ni - dist - rep + iss,/' \
  's/sh_open + dil - srep + siss,/sh_open + dil + siss,/' \
  's/+ nb, "debt\[y-1\] + net_borrowing"/+ 0.5 * nb, "debt[y-1] + net_borrowing"/' \
  's/div = L.put("dividends", y, L.v("dividends_declared", p),/div = L.put("dividends", y, 0.0,/'; do
  cp "$BAK" "$F"; sed -i "$mut" "$F"
  if cmp -s "$F" "$BAK"; then echo "NOT APPLIED: $mut"; fail=1; continue; fi
  if $PY -m pytest "$T" -q -x -p no:cacheprovider >/dev/null 2>&1; then
    echo "SURVIVED (bug not detected): $mut"; fail=1
  else
    echo "KILLED: $mut"
  fi
done
exit $fail
