"""Point-in-time snapshot builder (SPEC §5.1, §6.1, Phase 1).

Availability ("known-at") times:
- FinancialObservation: ``published_at``
- MarketObservation:    ``timestamp`` (a close is known at its own timestamp)
- CorporateActionEvent: ``announced_at`` (an action is *known* once announced; it is *effective*
                        for price/share adjustment from its ``ex_date`` (Asia/Shanghai date))

A snapshot at ``as_of`` is a pure function of the records with known-at <= as_of. Adding records
known later — new periods, restatements, prices, corporate actions or action revisions — cannot
change it (tested in tests/leakage/). The only post-as_of information that is used is the *count*
of excluded records, which lives in the build stats/quality report, never in the snapshot.

Restatements: all versions known at as_of are kept in ``version_history``; the value used is the
latest-published version. Earlier snapshots never see later versions.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from vms.pit.asof import AS_OF_DATE_RULE
from vms.quality.issues import IssueCollector
from vms.reporting.metadata import canonical_json
from vms.schemas import (BASE_CURRENCY, PRICE_ADJUSTING_ACTIONS, CorporateActionEvent, FinancialObservation,
                         InstrumentClassification, MarketObservation, QualityStatus, ReportingConvention,
                         SourceDescriptor, Versioning)
from vms.schemas.fields import FIELD_REGISTRY_VERSION, get_field

SNAPSHOT_VERSION = "PIT-SNAPSHOT-2"  # v2: + pit_complete, classification
CN_TZ = ZoneInfo("Asia/Shanghai")
Basis = Literal["cumulative_ytd", "standalone_quarter", "unknown_basis", "balance", "unclassified"]
_QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionRef(_M):
    source_id: str
    revision_id: str | None
    published_at: datetime
    value_cny: float | None


class SnapshotFinancial(_M):
    instrument_id: str
    period_end: date
    statement_type: str
    field_name: str
    basis: Basis
    value_cny: float | None = Field(description="CNY yuan; null if missing or not normalisable")
    quality_status: QualityStatus
    source_id: str
    revision_id: str | None
    published_at: datetime = Field(description="known-at time of the value (max of inputs if derived)")
    reported_value: float | None = None
    reported_unit_scale: str | None = None
    reported_currency: str | None = None
    version_history: list[VersionRef] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    formula: str | None = None
    flags: list[str] = Field(default_factory=list)


class SnapshotMarket(_M):
    instrument_id: str
    timestamp: datetime
    raw_close: float
    pit_adjustment_factor: float = Field(description="product of 1/share_ratio for known price-adjusting "
                                         "actions with ex_date in (obs date, as_of date]")
    pit_adjusted_close: float
    shares_outstanding: float | None
    currency: str
    source_id: str


class SnapshotCorporateAction(_M):
    event: CorporateActionEvent
    status: Literal["effective", "pending"]
    known_versions: int


class PITSnapshot(_M):
    snapshot_version: str = SNAPSHOT_VERSION
    field_registry_version: str = FIELD_REGISTRY_VERSION
    as_of_rule: dict = Field(default_factory=lambda: dict(AS_OF_DATE_RULE))
    instrument_id: str
    as_of: datetime
    base_currency: str = BASE_CURRENCY
    sources: dict[str, SourceDescriptor | None]
    pit_complete: bool = Field(description="all used sources declared FULL_HISTORY (PIT-INCOMPLETE-v1: Phase 9 "
                               "must exclude snapshots with pit_complete=false from unbiased metrics)")
    classification: InstrumentClassification | None = Field(description="latest classification known at as_of")
    financials: list[SnapshotFinancial]
    market: list[SnapshotMarket]
    corporate_actions: list[SnapshotCorporateAction]

    def get(self, field_name: str, period_end: date, basis: str | None = None) -> SnapshotFinancial | None:
        for f in self.financials:
            if f.field_name == field_name and f.period_end == period_end and (basis is None or f.basis == basis):
                return f
        return None


class BuildStats(_M):
    excluded_post_as_of: dict[str, int]


# ------------------------------------------------------------------ helpers
def local_date(ts: datetime) -> date:
    return ts.astimezone(CN_TZ).date()


def is_quarter_end(d: date) -> bool:
    return (d.month, d.day) in _QUARTER_ENDS


def prev_quarter_end_same_year(d: date) -> date | None:
    """Prior cumulative period within the same (calendar) fiscal year; None for Q1."""
    return {3: None, 6: date(d.year, 3, 31), 9: date(d.year, 6, 30), 12: date(d.year, 9, 30)}[d.month]


def _cny(o: FinancialObservation) -> float | None:
    if o.value is None or o.currency != BASE_CURRENCY:
        return None
    return o.value * o.unit_scale.multiplier


def _ref(o: FinancialObservation) -> str:
    return (f"{o.source_id}:{o.statement_type}.{o.field_name}@{o.period_end}"
            f"#{o.revision_id or '-'}@{o.published_at.isoformat()}")


def _close(a: float | None, b: float | None, rel: float = 1e-9) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-9)


# ------------------------------------------------------------------ financials
def _resolve_financial(group: list[FinancialObservation], ic: IssueCollector) -> tuple[FinancialObservation, list[VersionRef]]:
    uniq: dict[str, FinancialObservation] = {}
    for o in group:
        k = canonical_json(o.model_dump(mode="json", exclude={"ingested_at"}))
        if k in uniq:
            ic.add("DUPLICATE_RECORD", _ref(o))
        else:
            uniq[k] = o
    by_src: dict[str, list[FinancialObservation]] = defaultdict(list)
    for o in uniq.values():
        by_src[o.source_id].append(o)
    latest: list[FinancialObservation] = []
    for src in sorted(by_src):
        obs = sorted(by_src[src], key=lambda o: (o.published_at, o.revision_id or ""))
        top = [o for o in obs if o.published_at == obs[-1].published_at]
        if len({(_cny(o), o.value, o.currency, o.unit_scale) for o in top}) > 1:
            ic.add("CONFLICTING_VERSIONS", " vs ".join(_ref(o) for o in top))
        latest.append(obs[-1])
    if len(latest) > 1 and any(not _close(_cny(latest[0]), _cny(o)) for o in latest[1:]):
        ic.add("CONFLICTING_SOURCES", " vs ".join(_ref(o) for o in latest))
    chosen = max(latest, key=lambda o: (o.published_at, o.source_id, o.revision_id or ""))
    history = [VersionRef(source_id=o.source_id, revision_id=o.revision_id, published_at=o.published_at,
                          value_cny=_cny(o))
               for o in sorted(uniq.values(), key=lambda o: (o.published_at, o.source_id, o.revision_id or ""))]
    return chosen, history


def _basis(o: FinancialObservation, sources: dict[str, SourceDescriptor]) -> Basis:
    f = get_field(o.field_name)
    if f is None:
        return "unclassified"
    if f.kind == "stock":
        return "balance"
    sd = sources.get(o.source_id)
    conv = sd.reporting_convention if sd else ReportingConvention.UNKNOWN
    return {ReportingConvention.CN_CUMULATIVE_YTD: "cumulative_ytd",
            ReportingConvention.STANDALONE_QUARTER: "standalone_quarter",
            ReportingConvention.UNKNOWN: "unknown_basis"}[conv]


def _derive_standalone(rec: SnapshotFinancial, by_key: dict[tuple, SnapshotFinancial],
                       ic: IssueCollector) -> SnapshotFinancial:
    """Standalone quarter from CN cumulative YTD. Q1 = YTD(Q1); Qn = YTD(Qn) - YTD(Qn-1), same fiscal year."""
    pe = rec.period_end
    prev_pe = prev_quarter_end_same_year(pe)
    ref = f"{rec.field_name}@{rec.period_end}"
    common = dict(instrument_id=rec.instrument_id, period_end=pe, statement_type=rec.statement_type,
                  field_name=rec.field_name, basis="standalone_quarter", source_id=rec.source_id,
                  revision_id=rec.revision_id)
    inputs = [rec]
    if prev_pe is None:
        formula = f"standalone({pe}) = ytd({pe})"
    else:
        prev = by_key.get((prev_pe, rec.statement_type, rec.field_name))
        formula = f"standalone({pe}) = ytd({pe}) - ytd({prev_pe})"
        if prev is None or prev.basis != "cumulative_ytd":
            ic.add("CUMULATIVE_PRIOR_MISSING", f"{ref}: prior {prev_pe} not known at as_of")
            return SnapshotFinancial(**common, value_cny=None, quality_status=QualityStatus.MISSING,
                                     published_at=rec.published_at, derived_from=[_sref(rec)],
                                     formula=formula, flags=["CUMULATIVE_PRIOR_MISSING"])
        inputs.append(prev)
    if any(i.value_cny is None for i in inputs):
        ic.add("CUMULATIVE_PRIOR_MISSING", f"{ref}: input value null")
        return SnapshotFinancial(**common, value_cny=None, quality_status=QualityStatus.MISSING,
                                 published_at=max(i.published_at for i in inputs),
                                 derived_from=[_sref(i) for i in inputs], formula=formula,
                                 flags=["CUMULATIVE_INPUT_NULL"])
    value = inputs[0].value_cny - (inputs[1].value_cny if len(inputs) > 1 else 0.0)
    low = any(i.quality_status is QualityStatus.LOW_CONFIDENCE for i in inputs)
    ic.add("CUMULATIVE_DERIVED", ref)
    return SnapshotFinancial(**common, value_cny=value,
                             quality_status=QualityStatus.LOW_CONFIDENCE if low else QualityStatus.DERIVED,
                             published_at=max(i.published_at for i in inputs),
                             derived_from=[_sref(i) for i in inputs], formula=formula,
                             flags=["LOW_CONFIDENCE_INPUT"] if low else [])


def _sref(r: SnapshotFinancial) -> str:
    return (f"{r.source_id}:{r.statement_type}.{r.field_name}@{r.period_end}[{r.basis}]"
            f"#{r.revision_id or '-'}@{r.published_at.isoformat()}")


def _build_financials(obs: list[FinancialObservation], sources: dict[str, SourceDescriptor],
                      ic: IssueCollector) -> list[SnapshotFinancial]:
    groups: dict[tuple, list[FinancialObservation]] = defaultdict(list)
    for o in obs:
        groups[(o.period_end, o.statement_type, o.field_name)].append(o)
    out: list[SnapshotFinancial] = []
    for key in sorted(groups):
        chosen, history = _resolve_financial(groups[key], ic)
        f = get_field(chosen.field_name)
        flags: list[str] = []
        if f is None:
            ic.add("NON_CANONICAL_FIELD", f"{chosen.field_name}@{chosen.period_end}")
            flags.append("NON_CANONICAL_FIELD")
        elif f.statement_type != chosen.statement_type:
            ic.add("STATEMENT_TYPE_MISMATCH", f"{chosen.field_name}: {chosen.statement_type} != {f.statement_type}")
            flags.append("STATEMENT_TYPE_MISMATCH")
        if chosen.currency != BASE_CURRENCY:
            flags.append("CURRENCY_NOT_CNY")
        if not is_quarter_end(chosen.period_end):
            flags.append("IRREGULAR_PERIOD")
        out.append(SnapshotFinancial(
            instrument_id=chosen.instrument_id, period_end=chosen.period_end, statement_type=chosen.statement_type,
            field_name=chosen.field_name, basis=_basis(chosen, sources), value_cny=_cny(chosen),
            quality_status=chosen.quality_status, source_id=chosen.source_id, revision_id=chosen.revision_id,
            published_at=chosen.published_at, reported_value=chosen.value,
            reported_unit_scale=chosen.unit_scale.value, reported_currency=chosen.currency,
            version_history=history, flags=flags))
    by_key = {(r.period_end, r.statement_type, r.field_name): r for r in out}
    derived = [_derive_standalone(r, by_key, ic) for r in out
               if r.basis == "cumulative_ytd" and "IRREGULAR_PERIOD" not in r.flags]
    return sorted(out + derived, key=lambda r: (r.period_end, r.statement_type, r.field_name, r.basis))


# ------------------------------------------------------------------ corporate actions & market
def _build_actions(events: list[CorporateActionEvent], as_of: datetime,
                   ic: IssueCollector) -> list[SnapshotCorporateAction]:
    groups: dict[str, list[CorporateActionEvent]] = defaultdict(list)
    for e in events:
        groups[e.action_id].append(e)
    out = []
    for aid in sorted(groups):
        evs = sorted({canonical_json(e.model_dump(mode="json")): e for e in groups[aid]}.values(),
                     key=lambda e: (e.announced_at, e.revision_id or ""))
        top = [e for e in evs if e.announced_at == evs[-1].announced_at]
        if len(top) > 1:
            ic.add("CONFLICTING_CORPORATE_ACTION", aid)
        ev = evs[-1]
        out.append(SnapshotCorporateAction(event=ev, known_versions=len(evs),
                                           status="effective" if ev.ex_date <= local_date(as_of) else "pending"))
    return out


def _build_market(obs: list[MarketObservation], actions: list[SnapshotCorporateAction],
                  ic: IssueCollector) -> list[SnapshotMarket]:
    by_ts: dict[datetime, list[MarketObservation]] = defaultdict(list)
    for o in obs:
        by_ts[o.timestamp].append(o)
    adjusting = [a.event for a in actions if a.status == "effective" and a.event.action_type in PRICE_ADJUSTING_ACTIONS]
    out = []
    for ts in sorted(by_ts):
        group = by_ts[ts]
        distinct = {canonical_json(o.model_dump(mode="json", exclude={"adjusted_close", "corporate_action_version", "source_id"}))
                    for o in group}
        if len(distinct) > 1:
            ic.add("CONFLICTING_MARKET_OBS", f"{group[0].instrument_id}@{ts.isoformat()}")
        elif len(group) > 1:
            ic.add("DUPLICATE_RECORD", f"market {group[0].instrument_id}@{ts.isoformat()}")
        o = sorted(group, key=lambda m: m.source_id)[0]
        d = local_date(ts)
        factor = 1.0
        for e in adjusting:
            if e.ex_date > d:
                factor /= e.share_ratio
        out.append(SnapshotMarket(instrument_id=o.instrument_id, timestamp=ts, raw_close=o.raw_close,
                                  pit_adjustment_factor=factor, pit_adjusted_close=o.raw_close * factor,
                                  shares_outstanding=o.shares_outstanding, currency=o.currency,
                                  source_id=o.source_id))
    return out


# ------------------------------------------------------------------ entry point
def build_snapshot(*, instrument_id: str, as_of: datetime, financial: list[FinancialObservation],
                   market: list[MarketObservation], corporate_actions: list[CorporateActionEvent],
                   sources: dict[str, SourceDescriptor],
                   classifications: list[InstrumentClassification] | None = None,
                   ) -> tuple[PITSnapshot, BuildStats, IssueCollector]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    ic = IssueCollector()
    fin_i = [o for o in financial if o.instrument_id == instrument_id]
    mkt_i = [o for o in market if o.instrument_id == instrument_id]
    ca_i = [e for e in corporate_actions if e.instrument_id == instrument_id]
    fin_k = [o for o in fin_i if o.published_at <= as_of]
    mkt_k = [o for o in mkt_i if o.timestamp <= as_of]
    ca_k = [e for e in ca_i if e.announced_at <= as_of]
    stats = BuildStats(excluded_post_as_of={"financial": len(fin_i) - len(fin_k), "market": len(mkt_i) - len(mkt_k),
                                            "corporate_actions": len(ca_i) - len(ca_k)})
    actions = _build_actions(ca_k, as_of, ic)
    used_sources = sorted({o.source_id for o in fin_k} | {o.source_id for o in mkt_k} | {e.source_id for e in ca_k})
    cls_k = sorted((c for c in (classifications or []) if c.instrument_id == instrument_id and c.published_at <= as_of),
                   key=lambda c: (c.published_at, c.source_id))
    src_map = {s: sources.get(s) for s in used_sources}
    snap = PITSnapshot(instrument_id=instrument_id, as_of=as_of, sources=src_map,
                       pit_complete=all(sd is not None and sd.versioning is Versioning.FULL_HISTORY
                                        for sd in src_map.values()),
                       classification=cls_k[-1] if cls_k else None,
                       financials=_build_financials(fin_k, sources, ic),
                       market=_build_market(mkt_k, actions, ic), corporate_actions=actions)
    return snap, stats, ic
