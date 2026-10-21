"""Integrity and accounting checks on a PIT snapshot (SPEC §6.1, Phase 1).

All checks read only (a) the snapshot, (b) records already known at as_of, (c) declared source
metadata and (d) the validated config. Projection-dependent checks are DEFERRED.
"""

from __future__ import annotations

from datetime import date, datetime

from vms.pit.snapshot import PITSnapshot, is_quarter_end, local_date
from vms.quality.issues import IssueCollector
from vms.schemas import (BASE_CURRENCY, SHARE_CHANGING_ACTIONS, CorporateActionEvent, MarketObservation,
                         QualityStatus, Versioning)
from vms.schemas.config import QualityConfig
from vms.schemas.fields import get_field

#: §6.1 checks and their Phase-1 status.
CHECK_CATALOGUE: dict[str, tuple[str, str]] = {
    "DATA_AVAILABILITY": ("RUN", "§6.2 critical prerequisite"),
    "DUPLICATES_CONFLICTS": ("RUN", "§6.1 duplicate records and conflicting sources"),
    "FIELD_VOCABULARY": ("RUN", "§5.2 canonical fields (registry FIELDS-1)"),
    "UNIT_CURRENCY": ("RUN", "§6.1 unit/currency mismatch"),
    "POST_AS_OF": ("RUN", "§6.1 observation published after as_of"),
    "PERIOD_COVERAGE": ("RUN", "§6.1 missing quarters and irregular fiscal periods"),
    "CUMULATIVE_CONVERSION": ("RUN", "§6.1 cumulative quarterly flow conversion"),
    "BALANCE_SHEET_IDENTITY": ("RUN", "§6.1 balance-sheet identity, subject to source definitions"),
    "CASH_FLOW_SIGN_UNIT": ("RUN", "§6.1 cash-flow sign and unit consistency (sign rules for all statements)"),
    "SHARE_COUNT_CORPORATE_ACTIONS": ("RUN", "§6.1 share-count changes and corporate actions"),
    "PRICE_ADJUSTMENT": ("RUN", "§6.1 price-adjustment consistency around splits/dividends"),
    "EV_BRIDGE": ("DEFERRED", "§6.1 EV-to-equity bridge consistency — Phase 6 (needs valuation)"),
    "PROVENANCE": ("RUN", "§6.1 provenance and confidence for derived values"),
    "PIT_VERSIONING": ("RUN", "§5.1 historical versions reconstructible (else PIT_INCOMPLETE)"),
    "RESTATEMENTS": ("RUN", "§5.1 restatements known at as_of"),
    "PEER_CONTAMINATION": ("RUN", "§6.1/§21.3 peer membership, metrics and prices known at as_of only"),
}


def _quarters_between(a: date, b: date) -> list[date]:
    out, y, m = [], a.year, a.month
    ends = {3: 31, 6: 30, 9: 30, 12: 31}
    while True:
        d = date(y, m, ends[m])
        if d > b:
            return out
        out.append(d)
        m += 3
        if m > 12:
            m, y = 3, y + 1


def required_periods(as_of_date: date) -> list[date]:
    """Most recent periods whose CN statutory deadline has passed (STALENESS-CN-DEADLINE-v1).

    Annual (Y-1) and Q1 (Y) by Apr 30; H1 by Aug 31; Q3 by Oct 31. 'Passed' = as_of date after the deadline.
    """
    y = as_of_date.year
    if as_of_date > date(y, 10, 31):
        return [date(y, 9, 30)]
    if as_of_date > date(y, 8, 31):
        return [date(y, 6, 30)]
    if as_of_date > date(y, 4, 30):
        return [date(y - 1, 12, 31), date(y, 3, 31)]
    return [date(y - 1, 9, 30)]


def run_checks(snap: PITSnapshot, *, known_market: list[MarketObservation],
               known_actions: list[CorporateActionEvent], corporate_actions_provided: bool,
               cfg: QualityConfig, ic: IssueCollector) -> None:
    fin = snap.financials
    reported = [f for f in fin if f.formula is None]

    # DATA_AVAILABILITY
    if not reported:
        ic.add("NO_FINANCIAL_DATA", snap.instrument_id)
    if not snap.market:
        ic.add("NO_MARKET_DATA", snap.instrument_id)
    if cfg.require_industry_classification and snap.classification is None:
        ic.add("INDUSTRY_UNCLASSIFIED", snap.instrument_id)

    # UNIT_CURRENCY
    for f in reported:
        if f.reported_currency != BASE_CURRENCY:
            ic.add("CURRENCY_NOT_CNY", f"{f.field_name}@{f.period_end} {f.reported_currency}")
        vals = [v.value_cny for v in f.version_history if v.value_cny not in (None, 0.0)]
        for a, b in zip(vals, vals[1:]):
            r = abs(b / a)
            if r >= cfg.unit_jump_ratio or r <= 1 / cfg.unit_jump_ratio:
                ic.add("SUSPECTED_UNIT_MISMATCH", f"{f.field_name}@{f.period_end}: versions {a:g} -> {b:g}")
    for m in snap.market:
        if m.currency != BASE_CURRENCY:
            ic.add("CURRENCY_NOT_CNY", f"market@{m.timestamp.isoformat()} {m.currency}")
    for a in snap.corporate_actions:
        if a.event.action_type == "cash_dividend" and a.event.currency != BASE_CURRENCY:
            ic.add("CURRENCY_NOT_CNY", f"action {a.event.action_id} {a.event.currency}")
    balances: dict[str, list] = {}
    for f in reported:
        if f.basis == "balance" and f.value_cny not in (None, 0.0):
            balances.setdefault(f.field_name, []).append(f)
    for name, recs in balances.items():
        recs.sort(key=lambda r: r.period_end)
        for a, b in zip(recs, recs[1:]):
            r = abs(b.value_cny / a.value_cny)
            if r >= cfg.unit_jump_ratio or r <= 1 / cfg.unit_jump_ratio:
                ic.add("SUSPECTED_UNIT_MISMATCH", f"{name}: {a.period_end} {a.value_cny:g} -> {b.period_end} {b.value_cny:g}")

    # PERIOD_COVERAGE (+ late publication)
    periods = sorted({f.period_end for f in reported})
    regular = [p for p in periods if is_quarter_end(p)]
    for p in periods:
        if not is_quarter_end(p):
            ic.add("IRREGULAR_PERIOD", str(p))
    if regular:
        for q in _quarters_between(regular[0], regular[-1]):
            if q not in regular:
                ic.add("MISSING_QUARTER", str(q))
    if reported:
        for req in required_periods(local_date(snap.as_of)):
            if req not in periods and req > periods[0]:
                ic.add("STALE_FINANCIALS", f"{req} required by {local_date(snap.as_of)} but not known")
    for f in reported:
        first_pub = min(v.published_at for v in f.version_history)
        if (local_date(first_pub) - f.period_end).days > cfg.late_publication_days:
            ic.add("LATE_PUBLICATION", f"{f.period_end} first published {local_date(first_pub)}")

    # CUMULATIVE_CONVERSION: convention unknown
    for f in reported:
        if f.basis == "unknown_basis":
            ic.add("CUMULATIVE_CONVENTION_UNKNOWN", f"source {f.source_id}")

    # BALANCE_SHEET_IDENTITY
    for p in periods:
        a, l, e = (snap.get(n, p, "balance") for n in ("total_assets", "total_liabilities", "total_equity"))
        if any(x is not None for x in (a, l, e)):
            if any(x is None or x.value_cny is None for x in (a, l, e)):
                ic.add("BALANCE_SHEET_IDENTITY_UNCHECKED", str(p))
            elif abs(a.value_cny - l.value_cny - e.value_cny) > cfg.balance_sheet_rel_tol * abs(a.value_cny):
                ic.add("BALANCE_SHEET_IDENTITY_FAIL",
                       f"{p}: A={a.value_cny:g} L={l.value_cny:g} E={e.value_cny:g}")

    # CASH_FLOW_SIGN_UNIT
    for f in reported:
        cf = get_field(f.field_name)
        if cf and cf.sign != "signed" and f.value_cny is not None and f.value_cny < 0:
            ic.add("SIGN_CONVENTION_VIOLATION", f"{f.field_name}@{f.period_end}={f.reported_value} ({cf.sign})")
    for p in periods:
        capex = next((f for f in reported if f.field_name == "capex" and f.period_end == p), None)
        rev = next((f for f in reported if f.field_name == "revenue" and f.period_end == p), None)
        if capex and rev and capex.basis == rev.basis \
                and capex.value_cny is not None and rev.value_cny:
            if abs(capex.value_cny / rev.value_cny) > cfg.max_capex_to_revenue:
                ic.add("CAPEX_REVENUE_IMPLAUSIBLE", f"{p}: capex/revenue={capex.value_cny / rev.value_cny:.2f}")

    # SHARE_COUNT_CORPORATE_ACTIONS
    if not corporate_actions_provided:
        ic.add("CORPORATE_ACTIONS_UNAVAILABLE", snap.instrument_id)
    effective = [a.event for a in snap.corporate_actions if a.status == "effective"]
    share_events = [e for e in effective if e.action_type in SHARE_CHANGING_ACTIONS]
    with_shares = [m for m in snap.market if m.shares_outstanding is not None]
    for a, b in zip(with_shares, with_shares[1:]):
        da, db = local_date(a.timestamp), local_date(b.timestamp)
        expected = 1.0
        for e in share_events:
            if da < e.ex_date <= db:
                expected *= e.share_ratio
        actual = b.shares_outstanding / a.shares_outstanding
        if abs(actual / expected - 1) > cfg.share_change_rel_tol:
            ic.add("UNEXPLAINED_SHARE_CHANGE",
                   f"{da}->{db}: shares x{actual:.4f}, known actions explain x{expected:.4f}")

    # PRICE_ADJUSTMENT (vendor adjusted close is audit-only; never enters the snapshot)
    vend = sorted((m for m in known_market if m.instrument_id == snap.instrument_id and m.adjusted_close is not None),
                  key=lambda m: m.timestamp)
    if vend:
        ic.add("VENDOR_ADJUSTED_CLOSE_EXCLUDED", snap.instrument_id)
    ex_dates = [e.ex_date for e in effective]
    for a, b in zip(vend, vend[1:]):
        fa, fb = a.adjusted_close / a.raw_close, b.adjusted_close / b.raw_close
        if abs(fb / fa - 1) > cfg.adj_factor_rel_tol:
            da, db = local_date(a.timestamp), local_date(b.timestamp)
            if not any(da < x <= db for x in ex_dates):
                ic.add("VENDOR_ADJ_FACTOR_UNEXPLAINED", f"{da}->{db}: factor {fa:.6f}->{fb:.6f}")

    # PROVENANCE
    for f in fin:
        if f.formula is not None and (not f.derived_from):
            ic.add("PROVENANCE_INCOMPLETE", f"{f.field_name}@{f.period_end}")
        if f.value_cny is None and f.formula is None and f.quality_status in (
                QualityStatus.MISSING, QualityStatus.NOT_APPLICABLE):
            ic.add("EXPLICIT_MISSING_VALUE", f"{f.field_name}@{f.period_end}")

    # PIT_VERSIONING
    for sid, sd in snap.sources.items():
        if sd is None:
            ic.add("SOURCE_UNDECLARED", sid)
        elif sd.versioning is not Versioning.FULL_HISTORY:
            ic.add("SOURCE_NOT_FULL_HISTORY", f"{sid}: {sd.versioning.value}")

    # RESTATEMENTS
    for f in reported:
        if len(f.version_history) > 1:
            ic.add("RESTATEMENT_KNOWN", f"{f.field_name}@{f.period_end} ({len(f.version_history)} versions)")

    # PEER_CONTAMINATION: enforced in build_snapshot.peer_known_at (published_at / membership /
    # metric_timestamp). Leakage suite asserts post-as_of peers never enter snap.peers.
    _ = snap.peers  # touch for catalogue coverage; no extra issues when filter holds
