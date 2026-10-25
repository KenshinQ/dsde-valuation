"""Provider-neutral fetch_bundle for HiThink + Eastmoney NOTICE_DATE.

Local-first (HITHINK-LOCAL-FIRST-v1): ``prefer_local=True`` ⇒ zero REST even on
miss (empty local + flags). Recipe E (one REST upsert + re-read) only when
``prefer_local=False`` (``--refresh``). Never silently switch vendors. Never
echo API keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from vms.assumptions import cite
from vms.data.io import LoadResult
from vms.providers.hithink.lab import HiThinkUnavailable, load_lab_modules, redact_secrets
from vms.providers.hithink.local_store import count_statements, read_notices, read_statements
from vms.providers.hithink.mapping import map_statement_row, ms_to_shanghai_date
from vms.providers.hithink.paths import SOURCE_ID, duckdb_available, fund_db_path, market_db_path
from vms.providers.hithink.pit import (FALLBACK_SOURCE, NOTICE_SOURCE, build_notice_index,
                                       resolve_published_at)
from vms.providers.hithink.prices import bars_to_market_obs, recipe_e_ensure_prices, read_raw_bars
from vms.schemas.observations import (ReportingConvention, SourceDescriptor, Versioning)

TZ = ZoneInfo("Asia/Shanghai")


class HiThinkFetchError(RuntimeError):
    """Fetch/mapping failed for a requested ticker (no silent vendor swap)."""


@dataclass
class FetchDiagnostics:
    thscode: str
    prefer_local: bool
    assumptions: list[str] = field(default_factory=list)
    statement_counts: dict[str, int] = field(default_factory=dict)
    notice_count: int = 0
    notice_joined: int = 0
    notice_fallback: int = 0
    notice_unresolved: int = 0
    market_bars: int = 0
    unmapped_columns: int = 0
    mixed_dividend_interest_rows: int = 0
    flags: list[str] = field(default_factory=list)
    price_diag: dict[str, Any] = field(default_factory=dict)
    rest_notes: list[str] = field(default_factory=list)
    corporate_actions: str = "pending enrichment"
    shares_outstanding: str = "pending enrichment"
    industry: str = "pending enrichment"
    enrichment: dict[str, Any] = field(default_factory=dict)
    rest_calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        return redact_secrets({
            "thscode": self.thscode,
            "prefer_local": self.prefer_local,
            "assumptions": self.assumptions,
            "statement_counts": self.statement_counts,
            "notice_count": self.notice_count,
            "notice_joined": self.notice_joined,
            "notice_fallback": self.notice_fallback,
            "notice_unresolved": self.notice_unresolved,
            "market_bars": self.market_bars,
            "unmapped_columns": self.unmapped_columns,
            "mixed_dividend_interest_rows": self.mixed_dividend_interest_rows,
            "flags": sorted(set(self.flags)),
            "price_diag": self.price_diag,
            "rest_notes": self.rest_notes,
            "rest_calls": self.rest_calls,
            "corporate_actions": self.corporate_actions,
            "shares_outstanding": self.shares_outstanding,
            "industry": self.industry,
            "enrichment": self.enrichment,
            "source_id": SOURCE_ID,
            "versioning": "LATEST_ONLY",
            "pit_complete_expected": False,
        })


def _source_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        source_id=SOURCE_ID,
        reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
        versioning=Versioning.LATEST_ONLY,
        fiscal_year_end="12-31",
        description=(
            "HiThink fundamentals joined to Eastmoney NOTICE_DATE for published_at "
            "(HITHINK-PIT-NOTICE-v1). Store is LATEST_ONLY (no restatement history) → "
            "snapshots are PIT_INCOMPLETE / pit_complete=false."
        ),
    )


def _ensure_duckdb() -> None:
    if not duckdb_available():
        raise HiThinkUnavailable(
            "duckdb is required for the HiThink adapter; install with: "
            "pip install 'dsde-valuation[hithink]' (or uv pip install duckdb)"
        )


def _get_statements(store: Any, thscode: str, kind: str, period: str, *,
                    prefer_local: bool, min_local: int, limit: int) -> list[dict]:
    return store.get_statements(
        thscode, kind, period=period, limit=limit,
        prefer_local=prefer_local, min_local=min_local,
    )


def fetch_bundle(
    thscode: str,
    *,
    prefer_local: bool = True,
    min_local: int = 4,
    start: date | None = None,
    end: date | None = None,
    periods: tuple[str, ...] = ("annual", "quarterly"),
    include_prices: bool = True,
    fund_db: Path | str | None = None,
    market_db: Path | str | None = None,
    allow_report_date_fallback: bool = True,
    statement_limit: int = 40,
) -> tuple[LoadResult, FetchDiagnostics]:
    """Fetch a LoadResult-compatible bundle for one A-share thscode.

    Parameters
    ----------
    thscode:
        e.g. ``600519.SH``
    prefer_local:
        ``True`` (default / no ``--refresh``): local DuckDB only — miss ⇒ empty
        + flags, never Recipe E. ``False`` (``--refresh``): allow Recipe E REST.
    min_local:
        On refresh: minimum local statement rows to skip REST per kind/period.
        Ignored for REST gating when ``prefer_local=True`` (never REST).
    start, end:
        Optional price window (defaults: ~10y ending today Asia/Shanghai).
    """
    _ensure_duckdb()
    thscode = thscode.strip().upper()
    if "." not in thscode:
        raise HiThinkFetchError(f"thscode must include exchange suffix, got {thscode!r}")

    diag = FetchDiagnostics(
        thscode=thscode,
        prefer_local=prefer_local,
        assumptions=cite(
            "HITHINK-PIT-NOTICE-v1",
            "HITHINK-LATEST-ONLY-v1",
            "HITHINK-UNITS-YUAN-v1",
            "HITHINK-NO-VENDOR-QFQ-v1",
            "HITHINK-LOCAL-FIRST-v1",
            "HITHINK-REPORT-DATE-FALLBACK-v1",
            "HITHINK-FIELD-MAP-v1",
            "EM-CA-SHAREBONUS-v1",
            "EM-SHARES-EQUITY-v1",
            "EM-BS-LINES-v1",
            "INDUSTRY-SW-L1-PROXY-EM-v1",
            "INDUSTRY-NO-RECLASS-HISTORY-v1",
            "HITHINK-ALLOTMENT-DEFER-v1",
            "ASOF-DATE-CLOSE-v1",
            "PIT-INCOMPLETE-v1",
        ),
    )

    fdb = Path(fund_db) if fund_db else fund_db_path()
    mdb = Path(market_db) if market_db else market_db_path()
    if not fdb.is_file() and prefer_local:
        diag.flags.append("FUND_DB_MISSING")
    if prefer_local and not fdb.is_file():
        raise HiThinkFetchError(
            f"fundamentals DB missing at {fdb}; set HITHINK_FUND_DB_PATH or run with "
            f"--refresh after credentials are available (no silent vendor swap)"
        )

    labs = None
    prices_mod = None

    def _ensure_labs():
        nonlocal labs, prices_mod
        if labs is None:
            labs = load_lab_modules()
            prices_mod = labs["lib_prices"]
        return labs

    # --- notices: prefer_local ⇒ local only (miss = empty + flag); refresh ⇒ Recipe E ---
    notices: list = []
    if fdb.is_file():
        try:
            notices = read_notices(thscode, db_path=fdb)
        except Exception as e:  # noqa: BLE001 — empty/partial DuckDB fixtures
            if prefer_local:
                diag.flags.append(f"NOTICES_LOCAL_ERROR:{type(e).__name__}")
                notices = []
            else:
                raise
    if prefer_local:
        if not notices:
            diag.flags.append("NOTICES_LOCAL_MISS")
    elif len(notices) < max(min_local, 1):
        try:
            em_mod = _ensure_labs()["lib_em_notices"]
            notices = em_mod.get_em_notices(
                thscode, prefer_local=False, min_local=0, db_path=fdb,
            )
            diag.rest_calls += 1
            diag.rest_notes.append("notices: Recipe E EM upsert + re-read")
        except Exception as e:  # noqa: BLE001
            diag.rest_notes.append(f"notices REST: {type(e).__name__}: {str(e)[:120]}")
            if not notices:
                raise HiThinkFetchError(
                    f"no EM notices for {thscode} and REST unavailable: {e}"
                ) from e
    diag.notice_count = len(notices)
    notice_idx = build_notice_index(notices)

    # --- statements ---
    kind_map = {"income": "income", "balance": "balance", "cashflow": "cashflow"}
    financial = []
    for kind in ("income", "balance", "cashflow"):
        for period in periods:
            rows: list = []
            nloc = 0
            if fdb.is_file():
                try:
                    nloc = count_statements(thscode, kind, period, db_path=fdb)
                except Exception as e:  # noqa: BLE001
                    if prefer_local:
                        diag.flags.append(
                            f"STATEMENTS_LOCAL_ERROR:{kind}:{period}:{type(e).__name__}"
                        )
                        nloc = 0
                    else:
                        raise
            if prefer_local:
                # Zero REST even on miss / thin local (align enrich / R4 / R5).
                if fdb.is_file() and nloc > 0:
                    try:
                        rows = read_statements(
                            thscode, kind, period, db_path=fdb, limit=statement_limit,
                        )
                    except Exception as e:  # noqa: BLE001
                        diag.flags.append(
                            f"STATEMENTS_LOCAL_ERROR:{kind}:{period}:{type(e).__name__}"
                        )
                        rows = []
                if not rows:
                    diag.flags.append(f"STATEMENTS_LOCAL_MISS:{kind}:{period}")
            else:
                try:
                    store = _ensure_labs()["lib_fund_store"].FundStore(db_path=fdb)
                    # prefer_local=False ⇒ FundStore always Recipe E (ignore local count).
                    rows = _get_statements(
                        store, thscode, kind, period,
                        prefer_local=False, min_local=0, limit=statement_limit,
                    )
                    diag.rest_calls += 1
                    diag.rest_notes.append(
                        f"{kind}/{period}: Recipe E HiThink upsert + re-read"
                    )
                except Exception as e:  # noqa: BLE001
                    if fdb.is_file():
                        rows = read_statements(
                            thscode, kind, period, db_path=fdb, limit=statement_limit,
                        )
                        diag.rest_notes.append(
                            f"{kind}/{period}: REST failed ({type(e).__name__}); "
                            f"used local {len(rows)} rows"
                        )
                    else:
                        diag.rest_notes.append(
                            f"{kind}/{period}: {type(e).__name__}: {str(e)[:120]}"
                        )
                        rows = []
            diag.statement_counts[f"{kind}:{period}"] = len(rows)
            for row in rows:
                # Optional date filters on period_end
                pe = ms_to_shanghai_date(row.get("period_end_ms"))
                if pe is None:
                    continue
                if start is not None and pe < start:
                    continue
                if end is not None and pe > end:
                    continue
                resolved = resolve_published_at(
                    period_end_ms=row.get("period_end_ms"),
                    report_date_ms=row.get("report_date_ms"),
                    notice_by_period_end=notice_idx,
                    allow_report_date_fallback=allow_report_date_fallback,
                )
                if resolved is None:
                    diag.notice_unresolved += 1
                    diag.flags.append("STATEMENT_WITHOUT_PUBLISHED_AT")
                    continue
                if resolved.source == NOTICE_SOURCE:
                    diag.notice_joined += 1
                    qstat = "observed"
                else:
                    diag.notice_fallback += 1
                    qstat = "low_confidence"
                    diag.flags.append("PUBLISHED_AT_REPORT_DATE_FALLBACK")
                # Forbidden: period_end_ms as published_at
                if resolved.published_at.date() == resolved.period_end and resolved.source == NOTICE_SOURCE:
                    # NOTICE on period_end day is rare but legal; still 15:00 labeling.
                    pass
                obs, stats, flags = map_statement_row(
                    row, kind=kind_map[kind], instrument_id=thscode,
                    published_at=resolved.published_at, source_id=SOURCE_ID,
                    quality_status=qstat,
                    published_at_source=resolved.source,
                    revision_id=(
                        None if resolved.source == NOTICE_SOURCE
                        else f"published_at_source={FALLBACK_SOURCE}"
                    ),
                )
                # Stamp fallback flag on every obs revision_id already handled.
                if resolved.source == FALLBACK_SOURCE:
                    for i, o in enumerate(obs):
                        # ensure flag present
                        rid = o.revision_id or ""
                        if FALLBACK_SOURCE not in rid:
                            obs[i] = o.model_copy(update={
                                "revision_id": f"published_at_source={FALLBACK_SOURCE}",
                                "quality_status": "low_confidence",
                            })
                financial.extend(obs)
                diag.unmapped_columns += stats.unmapped
                diag.mixed_dividend_interest_rows += stats.mixed_dividend_interest
                diag.flags.extend(flags)

    # --- prices ---
    market = []
    if include_prices:
        today = datetime.now(TZ).date()
        p_end = end or today
        p_start = start or date(p_end.year - 10, 1, 1)
        try:
            bars_local: list = []
            if mdb.is_file():
                try:
                    bars_local = read_raw_bars(
                        thscode, start=p_start, end=p_end, db_path=mdb,
                    )
                except Exception as e:  # noqa: BLE001 — empty/partial marketdb
                    if prefer_local:
                        diag.flags.append(f"PRICES_LOCAL_ERROR:{type(e).__name__}")
                        bars_local = []
                    else:
                        raise
            pdiag: dict[str, Any] = {
                "bars": bars_local,
                "local_bars": len(bars_local),
                "source": "marketdb_raw_kline_daily",
                "prefer_local": prefer_local,
                "rest_used": False,
            }
            if prefer_local:
                if not bars_local:
                    diag.flags.append("PRICES_LOCAL_MISS")
                    pdiag["path"] = "local_miss_no_rest"
            else:
                try:
                    _ensure_labs()
                    pdiag = recipe_e_ensure_prices(
                        thscode, start=p_start, end=p_end, prefer_local=False,
                        lab_prices=prices_mod,
                    )
                    if pdiag.get("rest_used"):
                        diag.rest_calls += 1
                        diag.rest_notes.append("prices: Recipe E REST upsert + re-read")
                except Exception as e:  # noqa: BLE001
                    if bars_local:
                        pdiag = {
                            "bars": bars_local,
                            "local_bars": len(bars_local),
                            "source": "marketdb_raw_kline_daily",
                            "prefer_local": False,
                            "rest_used": False,
                        }
                        diag.rest_notes.append(
                            f"prices REST failed ({type(e).__name__}); using local"
                        )
                    else:
                        raise
            diag.price_diag = {
                k: v for k, v in pdiag.items() if k != "bars"
            }
            bars = pdiag.get("bars") or []
            market = bars_to_market_obs(bars, instrument_id=thscode, shares_outstanding=None)
            diag.market_bars = len(market)
            # Sanity: adjusted_close must all be null
            if any(m.adjusted_close is not None for m in market):
                raise HiThinkFetchError("internal error: vendor qfq leaked into adjusted_close")
        except Exception as e:  # noqa: BLE001
            if isinstance(e, HiThinkFetchError):
                raise
            diag.rest_notes.append(f"prices: {type(e).__name__}: {str(e)[:160]}")
            diag.flags.append("PRICES_UNAVAILABLE")

    if not financial and not market:
        raise HiThinkFetchError(
            f"no financials or market rows for {thscode} (prefer_local={prefer_local}); "
            "refusing silent vendor swap"
        )

    # --- Eastmoney enrichment: CA (announce dates), shares, industry proxy ---
    from vms.providers.eastmoney import enrich_bundle

    # period_end -> NOTICE date for aligning EM balance published_at (EM-BS-LINES-v1)
    notice_by_pe = {}
    for pe, nd in (notice_idx or {}).items():
        # notice_idx values may be date or richer objects
        if hasattr(nd, "year"):
            notice_by_pe[pe] = nd
        elif isinstance(nd, dict) and nd.get("notice_date") is not None:
            notice_by_pe[pe] = nd["notice_date"]
        elif hasattr(nd, "notice_date"):
            notice_by_pe[pe] = nd.notice_date
    enr = enrich_bundle(
        thscode,
        market=market,
        prefer_local=prefer_local,
        fund_db=fdb,
        notice_by_period_end=notice_by_pe,
    )
    market = enr.market
    if enr.financial:
        financial.extend(enr.financial)
    diag.enrichment = enr.diagnostics
    diag.assumptions = sorted(set(diag.assumptions) | set(enr.assumptions))
    n_ca = len(enr.corporate_actions)
    n_cls = len(enr.classifications)
    shares_n = sum(1 for m in market if m.shares_outstanding is not None)
    diag.corporate_actions = (
        f"{n_ca} events from EM RPT_SHAREBONUS_DET (EM-CA-SHAREBONUS-v1)"
        if n_ca else "empty — EM sharebonus miss or no announce+ex rows"
    )
    diag.shares_outstanding = (
        f"stamped on {shares_n}/{len(market)} bars via EM RPT_F10_EH_EQUITY (EM-SHARES-EQUITY-v1)"
        if shares_n else "null — EM equity miss"
    )
    if n_cls:
        c0 = enr.classifications[0]
        diag.industry = f"{c0.scheme}:{c0.industry} (INDUSTRY-SW-L1-PROXY-EM-v1)"
    else:
        diag.industry = "unset — EM F10 industry miss (production may BLOCK)"
    diag.market_bars = len(market)

    sources = {SOURCE_ID: _source_descriptor()}
    sources.update(enr.sources)

    load = LoadResult(
        financial=financial,
        market=market,
        corporate_actions=enr.corporate_actions,
        classifications=enr.classifications,
        sources=sources,
        corporate_actions_provided=True,  # enrichment path always declares CA table (may be empty)
        sources_provided=True,
        files={},
        errors=[],
    )
    return load, diag
