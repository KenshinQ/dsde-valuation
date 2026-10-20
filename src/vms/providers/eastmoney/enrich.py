"""Orchestrate Eastmoney enrichment: CA + shares + industry into a LoadResult-shaped bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from vms.providers.eastmoney import client as em_client
from vms.providers.eastmoney import store as em_store
from vms.providers.eastmoney.equity import apply_shares_to_market, equity_share_timeline
from vms.providers.eastmoney.industry import parse_company_survey, to_classification
from vms.providers.eastmoney.sharebonus import SOURCE_ID as CA_SOURCE, map_sharebonus_rows
from vms.schemas.observations import (CorporateActionEvent, InstrumentClassification, MarketObservation,
                                     ReportingConvention, SourceDescriptor, Versioning)

EQUITY_SOURCE = "em_f10_equity"
INDUSTRY_SOURCE = "em_f10_industry"


@dataclass
class EnrichmentResult:
    corporate_actions: list[CorporateActionEvent] = field(default_factory=list)
    classifications: list[InstrumentClassification] = field(default_factory=list)
    market: list[MarketObservation] = field(default_factory=list)
    sources: dict[str, SourceDescriptor] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)


def _ca_source() -> SourceDescriptor:
    return SourceDescriptor(
        source_id=CA_SOURCE,
        reporting_convention=ReportingConvention.UNKNOWN,
        versioning=Versioning.LATEST_ONLY,
        fiscal_year_end="12-31",
        description=(
            "Eastmoney RPT_SHAREBONUS_DET: PLAN_NOTICE_DATE/NOTICE_DATE → announced_at; "
            "EX_DIVIDEND_DATE → ex_date; per-10 cash/bonus ratios ÷10 (EM-CA-SHAREBONUS-v1)."
        ),
    )


def _equity_source() -> SourceDescriptor:
    return SourceDescriptor(
        source_id=EQUITY_SOURCE,
        reporting_convention=ReportingConvention.UNKNOWN,
        versioning=Versioning.LATEST_ONLY,
        fiscal_year_end="12-31",
        description=(
            "Eastmoney RPT_F10_EH_EQUITY: TOTAL_SHARES known at NOTICE_DATE "
            "(EM-SHARES-EQUITY-v1). Diluted shares not provided separately."
        ),
    )


def _industry_source() -> SourceDescriptor:
    return SourceDescriptor(
        source_id=INDUSTRY_SOURCE,
        reporting_convention=ReportingConvention.UNKNOWN,
        versioning=Versioning.LATEST_ONLY,
        fiscal_year_end="12-31",
        description=(
            "Eastmoney F10 CompanySurvey board+CSRC mapped to SW2021_L1 proxy names "
            "(INDUSTRY-SW-L1-PROXY-EM-v1). No official Shenwan L1 feed; no reclass history."
        ),
    )


def _ensure_sharebonus(thscode: str, *, prefer_local: bool, min_local: int, db: Path) -> tuple[list[dict], str]:
    local = em_store.read_sharebonus(thscode, db_path=db) if db.is_file() or True else []
    # ensure tables exist for count
    try:
        em_store.ensure_tables(db)
    except Exception:
        pass
    n = em_store.count_sharebonus(thscode, db_path=db)
    if prefer_local and n >= min_local:
        return em_store.read_sharebonus(thscode, db_path=db), "local"
    code = em_client.security_code_from_thscode(thscode)
    try:
        raw = em_client.fetch_datacenter_all(
            "RPT_SHAREBONUS_DET",
            filter_=f'(SECURITY_CODE="{code}")',
            sort_columns="REPORT_DATE",
            referer="https://data.eastmoney.com/yjfp/",
        )
        em_store.upsert_sharebonus(thscode, raw, db_path=db)
        return em_store.read_sharebonus(thscode, db_path=db), "rest_upsert"
    except Exception as e:  # noqa: BLE001
        if n > 0:
            return em_store.read_sharebonus(thscode, db_path=db), f"rest_failed_local:{type(e).__name__}"
        raise


def _ensure_equity(thscode: str, *, prefer_local: bool, min_local: int, db: Path) -> tuple[list[dict], str]:
    try:
        em_store.ensure_tables(db)
    except Exception:
        pass
    n = em_store.count_equity(thscode, db_path=db)
    if prefer_local and n >= min_local:
        return em_store.read_equity(thscode, db_path=db), "local"
    code = em_client.security_code_from_thscode(thscode)
    try:
        raw = em_client.fetch_datacenter_all(
            "RPT_F10_EH_EQUITY",
            filter_=f'(SECURITY_CODE="{code}")',
            sort_columns="NOTICE_DATE",
            referer="https://data.eastmoney.com/",
        )
        em_store.upsert_equity(thscode, raw, db_path=db)
        return em_store.read_equity(thscode, db_path=db), "rest_upsert"
    except Exception as e:  # noqa: BLE001
        if n > 0:
            return em_store.read_equity(thscode, db_path=db), f"rest_failed_local:{type(e).__name__}"
        raise


def _ensure_industry(thscode: str, *, prefer_local: bool, db: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        em_store.ensure_tables(db)
    except Exception:
        pass
    local = em_store.read_industry(thscode, db_path=db)
    if prefer_local and local and local.get("sw_l1_proxy"):
        return local, "local"
    try:
        body = em_client.fetch_company_survey(thscode)
        parsed = parse_company_survey(body)
        em_store.upsert_industry(thscode, parsed, db_path=db)
        return em_store.read_industry(thscode, db_path=db), "rest_upsert"
    except Exception as e:  # noqa: BLE001
        if local:
            return local, f"rest_failed_local:{type(e).__name__}"
        raise


def enrich_bundle(
    thscode: str,
    *,
    market: list[MarketObservation],
    prefer_local: bool = True,
    min_local_ca: int = 1,
    min_local_equity: int = 1,
    fund_db: Path | str | None = None,
    enable_ca: bool = True,
    enable_shares: bool = True,
    enable_industry: bool = True,
) -> EnrichmentResult:
    """Fetch/map EM enrichment. Local DuckDB cache first; REST on miss.

    Does **not** use HiThink adjustment-factors announced_at (unavailable).
    Allotment/rights from marketdb without announce dates remain deferred.
    """
    from vms.assumptions import cite

    from vms.providers.hithink.paths import fund_db_path
    db = Path(fund_db) if fund_db else fund_db_path()

    res = EnrichmentResult(
        market=list(market),
        assumptions=cite(
            "EM-CA-SHAREBONUS-v1",
            "EM-SHARES-EQUITY-v1",
            "INDUSTRY-SW-L1-PROXY-EM-v1",
            "INDUSTRY-NO-RECLASS-HISTORY-v1",
            "HITHINK-ALLOTMENT-DEFER-v1",
        ),
    )
    diag: dict[str, Any] = {"thscode": thscode, "prefer_local": prefer_local}

    if enable_ca:
        try:
            rows, path = _ensure_sharebonus(thscode, prefer_local=prefer_local, min_local=min_local_ca, db=db)
            events, stats = map_sharebonus_rows(rows, instrument_id=thscode)
            res.corporate_actions = events
            res.sources[CA_SOURCE] = _ca_source()
            diag["sharebonus"] = {"path": path, "rows": len(rows), **stats, "events": len(events)}
        except Exception as e:  # noqa: BLE001
            diag["sharebonus"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}

    if enable_shares:
        try:
            rows, path = _ensure_equity(thscode, prefer_local=prefer_local, min_local=min_local_equity, db=db)
            timeline = equity_share_timeline(rows)
            res.market = apply_shares_to_market(res.market, timeline)
            res.sources[EQUITY_SOURCE] = _equity_source()
            stamped = sum(1 for m in res.market if m.shares_outstanding is not None)
            diag["equity"] = {
                "path": path, "rows": len(rows), "timeline_points": len(timeline),
                "market_bars_with_shares": stamped,
            }
        except Exception as e:  # noqa: BLE001
            diag["equity"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}

    if enable_industry:
        try:
            parsed, path = _ensure_industry(thscode, prefer_local=prefer_local, db=db)
            cls = None
            if parsed:
                # store row may use date objects
                p = {
                    "sw_l1_proxy": parsed.get("sw_l1_proxy"),
                    "listing_date": parsed.get("listing_date"),
                    "em_board": parsed.get("em_board"),
                    "csrc_industry": parsed.get("csrc_industry"),
                    "map_reason": parsed.get("map_reason"),
                }
                if hasattr(p["listing_date"], "isoformat") is False and p["listing_date"]:
                    try:
                        p["listing_date"] = date.fromisoformat(str(p["listing_date"])[:10])
                    except ValueError:
                        p["listing_date"] = None
                cls = to_classification(p, instrument_id=thscode)
            if cls is not None:
                res.classifications = [cls]
                res.sources[INDUSTRY_SOURCE] = _industry_source()
            diag["industry"] = {
                "path": path,
                "em_board": (parsed or {}).get("em_board"),
                "csrc_industry": (parsed or {}).get("csrc_industry"),
                "sw_l1_proxy": (parsed or {}).get("sw_l1_proxy"),
                "listing_date": str((parsed or {}).get("listing_date") or ""),
                "classified": cls is not None,
            }
        except Exception as e:  # noqa: BLE001
            diag["industry"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}

    res.diagnostics = diag
    return res
