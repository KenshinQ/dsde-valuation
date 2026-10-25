"""R5: deepen subject own-hist TE+OEI+shares+raw_close for Track B (RIM-SUBJECT-HIST-DEPTH-v1).

Local-first loader aligned with R4 peer panel helpers. Recipe E / EM REST only when
``prefer_local=False`` (explicit ``--refresh``). Never invent OEI; never lower
MIN_HIST_PB_POINTS; never default pb=2.0; never lift industry.unsupported.

Year-level skip funnel is produced by ``historical_common_pb`` after merge; this
module supplies the deeper LoadResult plane so scarcity is data-honest, not unload-driven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from vms.assumptions import cite
from vms.data.io import LoadResult
from vms.methods.rim.bank_peer_panel import (
    TickerPathDiag,
    _load_bank_f10_for_ticker,
    _load_equity_shares,
    _load_prices_for_ticker,
    _load_te_for_ticker,
)
from vms.providers.eastmoney.bank_f10 import SOURCE_ID as BANK_F10_SOURCE
from vms.providers.hithink.paths import SOURCE_ID as HT_SOURCE, fund_db_path, market_db_path
from vms.schemas.observations import (
    FinancialObservation,
    MarketObservation,
    ReportingConvention,
    SourceDescriptor,
    Versioning,
)

EQUITY_SOURCE = "em_f10_equity"

SUBJECT_HIST_SOURCE_ID = "fi_subject_hist_depth_v1"
DEFAULT_SUBJECT_F10_MAX_ANNUAL = 20
DEFAULT_SUBJECT_STATEMENT_LIMIT = 40
DEFAULT_SUBJECT_PRICE_LOOKBACK_YEARS = 20


@dataclass
class SubjectHistDepthReport:
    instrument_id: str
    as_of: str
    financial: list[FinancialObservation]
    market: list[MarketObservation]
    path_diag: TickerPathDiag
    flags: list[str]
    assumption_ids: list[str]
    rest_calls: int = 0
    detail: str = ""
    source_id: str = SUBJECT_HIST_SOURCE_ID
    prefer_local: bool = True
    n_financial_added: int = 0
    n_market_added: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "as_of": self.as_of,
            "n_financial": len(self.financial),
            "n_market": len(self.market),
            "n_financial_added": self.n_financial_added,
            "n_market_added": self.n_market_added,
            "path_diag": self.path_diag.as_dict(),
            "flags": list(self.flags),
            "assumption_ids": list(self.assumption_ids),
            "rest_calls": self.rest_calls,
            "detail": self.detail,
            "source_id": self.source_id,
            "prefer_local": self.prefer_local,
            "notes": list(self.notes),
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "min_hist_pb_points_unchanged": True,
            "no_invent_oei": True,
            "no_default_pb_2": True,
        }


def _fin_key(o: FinancialObservation) -> tuple[str, date, str]:
    return (o.instrument_id, o.period_end, o.field_name)


def _mkt_key(o: MarketObservation) -> tuple[str, datetime]:
    return (o.instrument_id, o.timestamp)


def _ensure_source(load: LoadResult, source_id: str) -> None:
    if source_id in load.sources:
        return
    load.sources[source_id] = SourceDescriptor(
        source_id=source_id,
        reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
        versioning=Versioning.FULL_HISTORY,
    )
    load.sources_provided = True


def build_subject_hist_depth(
    *,
    instrument_id: str,
    as_of: datetime,
    prefer_local: bool = True,
    fund_db: Path | str | None = None,
    market_db: Path | str | None = None,
    allow_report_date_fallback: bool = True,
    statement_limit: int = DEFAULT_SUBJECT_STATEMENT_LIMIT,
    price_lookback_years: int = DEFAULT_SUBJECT_PRICE_LOOKBACK_YEARS,
    max_annual_f10: int = DEFAULT_SUBJECT_F10_MAX_ANNUAL,
) -> SubjectHistDepthReport:
    """Load deep subject TE + bank_f10 OEI/MI + raw_close/shares for own-hist P/B.

    ``prefer_local=True`` ⇒ zero REST even on miss (path diag only).
    ``prefer_local=False`` ⇒ allow Recipe E / EM upsert; fail → local/empty; never invent OEI.
    """
    aids = cite(
        "RIM-SUBJECT-HIST-DEPTH-v1",
        "RIM-EXIT-OWN-PB-HIST-v1",
        "RIM-COMMON-EQUITY-v1",
        "HITHINK-LOCAL-FIRST-v1",
        "EM-FI-F10-v1",
        "EM-SHARES-EQUITY-v1",
        "HITHINK-NO-VENDOR-QFQ-v1",
    )
    flags: list[str] = [
        "SUBJECT_HIST_DEPTH_BUILDER",
        "NO_INDUSTRY_UNSUPPORTED_LIFT",
        "NO_INVENT_OEI",
        "MIN_HIST_PB_POINTS_UNCHANGED",
        "FORBID_DEFAULT_PB_CENTER_2",
    ]
    if prefer_local:
        flags.append("SUBJECT_HIST_PREFER_LOCAL")
    else:
        flags.append("SUBJECT_HIST_REFRESH_ALLOWED")

    fdb = Path(fund_db) if fund_db else fund_db_path()
    mdb = Path(market_db) if market_db else market_db_path()
    diag = TickerPathDiag(instrument_id=instrument_id)

    te = _load_te_for_ticker(
        instrument_id,
        fund_db=fdb,
        prefer_local=prefer_local,
        allow_report_date_fallback=allow_report_date_fallback,
        statement_limit=statement_limit,
        diag=diag,
    )
    f10 = _load_bank_f10_for_ticker(
        instrument_id,
        fund_db=fdb,
        prefer_local=prefer_local,
        diag=diag,
        max_annual=max_annual_f10,
    )
    financial = list(te) + list(f10)

    p_end = as_of.date()
    p_start = date(p_end.year - int(price_lookback_years), 1, 1)
    mkt = _load_prices_for_ticker(
        instrument_id,
        market_db=mdb,
        prefer_local=prefer_local,
        start=p_start,
        end=p_end,
        diag=diag,
    )
    mkt = _load_equity_shares(
        instrument_id, fund_db=fdb, prefer_local=prefer_local, market=mkt, diag=diag,
    )

    if prefer_local and diag.rest_calls > 0:
        flags.append("SUBJECT_HIST_REST_UNEXPECTED")
    if diag.te_obs == 0:
        flags.append("SUBJECT_HIST_TE_EMPTY")
    if diag.bank_f10_obs == 0:
        flags.append("SUBJECT_HIST_BANK_F10_EMPTY")
    if diag.market_bars == 0:
        flags.append("SUBJECT_HIST_PRICES_EMPTY")

    detail = (
        f"te_obs={diag.te_obs}; bank_f10_obs={diag.bank_f10_obs}; "
        f"market_bars={diag.market_bars}; equity_rows={diag.equity_rows}; "
        f"rest_calls={diag.rest_calls}; prefer_local={prefer_local}; "
        f"max_annual_f10={max_annual_f10}; price_lookback_years={price_lookback_years}"
    )
    return SubjectHistDepthReport(
        instrument_id=instrument_id,
        as_of=as_of.isoformat(),
        financial=financial,
        market=mkt,
        path_diag=diag,
        flags=sorted(set(flags)),
        assumption_ids=aids,
        rest_calls=diag.rest_calls,
        detail=detail,
        prefer_local=prefer_local,
        notes=list(diag.notes),
    )


def merge_subject_hist_into_load(
    load: LoadResult,
    depth: SubjectHistDepthReport,
) -> LoadResult:
    """Merge deepened subject observations into ``load`` (append-only for new keys).

    Existing (instrument, period_end, field) financial rows win (no overwrite) so
    NOTICE-aligned ingest is preserved; missing years/fields from depth are appended.
    Market bars: existing timestamps win; missing timestamps appended. Shares on an
    existing bar are filled only when the load bar has shares_outstanding is None
    and the depth bar has a positive share count.
    """
    fin_have = {_fin_key(o) for o in load.financial}
    fin_added: list[FinancialObservation] = []
    for o in depth.financial:
        k = _fin_key(o)
        if k in fin_have:
            continue
        fin_added.append(o)
        fin_have.add(k)

    mkt_by_ts = {_mkt_key(o): o for o in load.market}
    mkt_added: list[MarketObservation] = []
    mkt_updated: list[MarketObservation] = []
    for o in depth.market:
        k = _mkt_key(o)
        if k not in mkt_by_ts:
            mkt_added.append(o)
            mkt_by_ts[k] = o
            continue
        cur = mkt_by_ts[k]
        if (
            cur.instrument_id == depth.instrument_id
            and (cur.shares_outstanding is None or not (cur.shares_outstanding > 0))
            and o.shares_outstanding is not None
            and o.shares_outstanding > 0
        ):
            stamped = cur.model_copy(update={"shares_outstanding": float(o.shares_outstanding)})
            mkt_by_ts[k] = stamped
            mkt_updated.append(stamped)

    # Rebuild market list preserving original order then append new.
    if mkt_updated:
        upd_keys = {_mkt_key(o) for o in mkt_updated}
        new_market: list[MarketObservation] = []
        for o in load.market:
            k = _mkt_key(o)
            new_market.append(mkt_by_ts[k] if k in upd_keys else o)
        new_market.extend(mkt_added)
        market_out = new_market
    else:
        market_out = list(load.market) + mkt_added

    depth.n_financial_added = len(fin_added)
    depth.n_market_added = len(mkt_added)
    if fin_added or mkt_added or mkt_updated:
        depth.flags = sorted(set(depth.flags) | {"SUBJECT_HIST_MERGED_INTO_LOAD"})
    if mkt_updated:
        depth.flags = sorted(set(depth.flags) | {"SUBJECT_HIST_SHARES_STAMPED"})

    _ensure_source(load, HT_SOURCE)
    _ensure_source(load, BANK_F10_SOURCE)
    _ensure_source(load, EQUITY_SOURCE)
    _ensure_source(load, SUBJECT_HIST_SOURCE_ID)

    return LoadResult(
        financial=list(load.financial) + fin_added,
        market=market_out,
        corporate_actions=list(load.corporate_actions),
        classifications=list(load.classifications),
        peers=list(load.peers),
        sources=dict(load.sources),
        corporate_actions_provided=load.corporate_actions_provided,
        sources_provided=True if load.sources else load.sources_provided,
        files=dict(load.files),
        errors=list(load.errors),
    )
