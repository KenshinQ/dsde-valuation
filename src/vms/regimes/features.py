"""Fundamental regime features from PIT financial records ONLY (SPEC §7.4).

The function signature takes snapshot *financial* records, not a snapshot. Market data (prices,
returns, market caps) therefore cannot reach regime inference. tests/leakage enforces this structurally
(AST scan) and behaviourally (prices perturbed => identical posteriors).

Features at each period end p (TTM = trailing four standalone quarters, or the FY value at 12-31):
- revenue_growth_yoy   = TTM_revenue(p) / TTM_revenue(p - 1y) - 1   (prior > 0)
- ebit_margin_ttm      = TTM_recurring_EBIT(p) / TTM_revenue(p)
- ebit_margin_change   = margin(p) - margin(p - 1y)
Recurring EBIT subtracts non_recurring_items_pretax when all of the window's values are known
(else reported EBIT, flagged ONE_OFFS_NOT_ADJUSTED).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from vms.pit.snapshot import SnapshotFinancial
from vms.regimes.schemas import FeatureRow

_FIELDS = ("revenue", "ebit", "non_recurring_items_pretax")


def _minus_year(d: date) -> date:
    return date(d.year - 1, d.month, d.day)


def _quarters_back(p: date) -> list[date]:
    ends = [(3, 31), (6, 30), (9, 30), (12, 31)]
    i = ends.index((p.month, p.day))
    out = []
    y = p.year
    for _ in range(4):
        out.append(date(y, *ends[i]))
        i -= 1
        if i < 0:
            i, y = 3, y - 1
    return out


def _ttm(recs: dict, name: str, p: date) -> tuple[float | None, list[SnapshotFinancial], str | None]:
    """(value, inputs, basis-used). Standalone quarters preferred; FY cumulative at 12-31 otherwise."""
    qs = [recs.get((name, q, "standalone_quarter")) for q in _quarters_back(p)]
    if all(q is not None and q.value_cny is not None for q in qs):
        return sum(q.value_cny for q in qs), qs, "quarterly"
    if (p.month, p.day) == (12, 31):
        fy = recs.get((name, p, "cumulative_ytd"))
        if fy is not None and fy.value_cny is not None:
            return fy.value_cny, [fy], "annual"
    return None, [], None


def fundamental_features(financials: Sequence[SnapshotFinancial]) -> list[FeatureRow]:
    recs: dict[tuple[str, date, str], SnapshotFinancial] = {}
    for f in financials:
        if f.field_name in _FIELDS and f.basis in ("standalone_quarter", "cumulative_ytd"):
            recs[(f.field_name, f.period_end, f.basis)] = f
    periods = sorted({k[1] for k in recs if k[0] == "revenue"})
    rows: list[FeatureRow] = []
    cache: dict[date, tuple] = {}

    def margin_at(p: date):  # noqa: ANN202
        if p in cache:
            return cache[p]
        rev, rin, cad = _ttm(recs, "revenue", p)
        ebit, ein, _ = _ttm(recs, "ebit", p)
        nri, nin, _ = _ttm(recs, "non_recurring_items_pretax", p)
        flags = []
        m = None
        if rev is not None and ebit is not None and rev > 0:
            if nri is not None:
                ebit -= nri
            else:
                flags.append("ONE_OFFS_NOT_ADJUSTED")
            m = ebit / rev
        cache[p] = (rev, m, cad, [*rin, *ein, *nin], flags)
        return cache[p]

    for p in periods:
        rev, m, cad, ins, flags = margin_at(p)
        if rev is None or cad is None:
            continue
        prev = _minus_year(p) if not (p.month == 2 and p.day == 29) else date(p.year - 1, 2, 28)
        prev_rev, prev_m, _, prev_ins, _ = margin_at(prev)
        flags = list(flags)
        g = rev / prev_rev - 1 if prev_rev is not None and prev_rev > 0 else None
        dm = m - prev_m if m is not None and prev_m is not None else None
        if g is None and dm is None:
            continue   # no yoy information at all: the period is not classified (never a fabricated state)
        if g is None:
            flags.append("NO_PRIOR_YEAR_REVENUE")
        if dm is None:
            flags.append("NO_PRIOR_YEAR_MARGIN")
        used = [*ins, *(prev_ins if g is not None or dm is not None else [])]
        if any(u.quality_status.value in ("low_confidence",) for u in used):
            flags.append("LOW_CONFIDENCE_INPUT")
        if any(u.formula is not None for u in used):
            flags.append("DERIVED_INPUT")
        refs = sorted({f"snapshot:{u.source_id}:{u.statement_type}.{u.field_name}@{u.period_end}[{u.basis}]"
                       f"#{u.revision_id or '-'}" for u in used})
        rows.append(FeatureRow(period_end=p, cadence=cad, revenue_growth_yoy=g, ebit_margin_ttm=m,
                               ebit_margin_change_yoy=dm, known_at=max(u.published_at for u in used),
                               refs=refs, flags=sorted(set(flags))))
    # single cadence: if any quarterly rows exist, keep quarterly rows only (no mixed step lengths)
    if any(r.cadence == "quarterly" for r in rows):
        rows = [r for r in rows if r.cadence == "quarterly"]
    return rows
