"""R4: multi-instrument deposit-taking FI peer panel (RIM-FI-PEER-PANEL-v1).

Local-first loader that merges TE (HiThink balance) + EM bank_f10 OEI/MI +
raw_close/shares into a multi-ticker panel so R3 ``build_fi_peer_observations``
is not subject-only. Recipe E / EM REST only when ``prefer_local=False``
(explicit ``--refresh``). Never invent OEI; never lift industry.unsupported;
never treat profile FINANCIAL_INSTITUTION alone as deposit-taking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from vms.assumptions import cite
from vms.methods.rim.bank_peers import (
    LEAN_CURATED_DEPOSIT_TAKING_FI,
    discover_bank_candidates,
)
from vms.providers.eastmoney import client as em_client
from vms.providers.eastmoney import store as em_store
from vms.providers.eastmoney.bank_f10 import SOURCE_ID as BANK_F10_SOURCE
from vms.providers.eastmoney.bank_f10 import map_bank_f10_rows
from vms.providers.eastmoney.equity import apply_shares_to_market, equity_share_timeline
from vms.providers.eastmoney.industry import (
    deposit_taking_fi_sw_label,
    parse_company_survey,
    to_classification,
)
from vms.providers.hithink.local_store import read_notices, read_statements
from vms.providers.hithink.mapping import map_statement_row, ms_to_shanghai_date
from vms.providers.hithink.paths import SOURCE_ID as HT_SOURCE, fund_db_path, market_db_path
from vms.providers.hithink.pit import (
    FALLBACK_SOURCE,
    NOTICE_SOURCE,
    build_notice_index,
    resolve_published_at,
)
from vms.providers.hithink.prices import bars_to_market_obs, read_raw_bars
from vms.schemas.observations import (
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
)

PANEL_SOURCE_ID = "fi_peer_panel_v1"


@dataclass
class TickerPathDiag:
    instrument_id: str
    te_path: str = "unset"
    te_obs: int = 0
    bank_f10_path: str = "unset"
    bank_f10_obs: int = 0
    equity_path: str = "unset"
    equity_rows: int = 0
    prices_path: str = "unset"
    market_bars: int = 0
    industry_path: str = "unset"
    classified: bool = False
    rest_calls: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "te_path": self.te_path,
            "te_obs": self.te_obs,
            "bank_f10_path": self.bank_f10_path,
            "bank_f10_obs": self.bank_f10_obs,
            "equity_path": self.equity_path,
            "equity_rows": self.equity_rows,
            "prices_path": self.prices_path,
            "market_bars": self.market_bars,
            "industry_path": self.industry_path,
            "classified": self.classified,
            "rest_calls": self.rest_calls,
            "errors": list(self.errors),
            "notes": list(self.notes),
        }


@dataclass
class FiPeerPanelReport:
    subject_instrument_id: str
    as_of: str
    candidate_ids: list[str]
    financial: list[FinancialObservation]
    market: list[MarketObservation]
    classifications: list[InstrumentClassification]
    ticker_diagnostics: list[TickerPathDiag]
    flags: list[str]
    assumption_ids: list[str]
    rest_calls: int = 0
    detail: str = ""
    source_id: str = PANEL_SOURCE_ID

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject_instrument_id": self.subject_instrument_id,
            "as_of": self.as_of,
            "candidate_ids": list(self.candidate_ids),
            "n_financial": len(self.financial),
            "n_market": len(self.market),
            "n_classifications": len(self.classifications),
            "ticker_diagnostics": [t.as_dict() for t in self.ticker_diagnostics],
            "flags": list(self.flags),
            "assumption_ids": list(self.assumption_ids),
            "rest_calls": self.rest_calls,
            "detail": self.detail,
            "source_id": self.source_id,
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
        }


def _ensure_tables(db: Path) -> None:
    try:
        em_store.ensure_tables(db)
    except Exception:
        pass


def _load_te_for_ticker(
    thscode: str,
    *,
    fund_db: Path,
    prefer_local: bool,
    allow_report_date_fallback: bool,
    statement_limit: int,
    diag: TickerPathDiag,
) -> list[FinancialObservation]:
    """Map HiThink annual balance → TE (and related). Local-only unless refresh."""
    out: list[FinancialObservation] = []
    if not fund_db.is_file():
        diag.te_path = "fund_db_missing"
        diag.errors.append("FUND_DB_MISSING")
        return out

    try:
        notices = read_notices(thscode, db_path=fund_db)
    except Exception as e:  # noqa: BLE001 — empty/partial DuckDB in unit fixtures
        notices = []
        diag.notes.append(f"NOTICES_UNAVAILABLE:{type(e).__name__}")
    notice_idx = build_notice_index(notices)
    try:
        rows = read_statements(
            thscode, "balance", "annual", db_path=fund_db, limit=statement_limit,
        )
    except Exception as e:  # noqa: BLE001
        rows = []
        diag.te_path = f"local_error:{type(e).__name__}"
        diag.errors.append(f"TE_LOCAL:{type(e).__name__}")
        return out
    if rows:
        diag.te_path = "local"
    elif prefer_local:
        diag.te_path = "local_miss_no_rest"
        diag.notes.append("TE_LOCAL_MISS")
        return out
    else:
        # Refresh path: one Recipe E via lab FundStore; fail → leave empty (no invent).
        try:
            from vms.providers.hithink.adapter import _get_statements
            from vms.providers.hithink.lab import load_lab_modules

            labs = load_lab_modules()
            store = labs["lib_fund_store"].FundStore(db_path=fund_db)
            rows = _get_statements(
                store, thscode, "balance", "annual",
                prefer_local=False, min_local=0, limit=statement_limit,
            )
            diag.te_path = "rest_upsert"
            diag.rest_calls += 1
            diag.notes.append("TE_RECIPE_E")
        except Exception as e:  # noqa: BLE001
            diag.te_path = f"rest_failed:{type(e).__name__}"
            diag.errors.append(f"TE_REST:{type(e).__name__}")
            return out

    for row in rows:
        resolved = resolve_published_at(
            period_end_ms=row.get("period_end_ms"),
            report_date_ms=row.get("report_date_ms"),
            notice_by_period_end=notice_idx,
            allow_report_date_fallback=allow_report_date_fallback,
        )
        if resolved is None:
            continue
        qstat = "observed" if resolved.source == NOTICE_SOURCE else "low_confidence"
        rev = None if resolved.source == NOTICE_SOURCE else f"published_at_source={FALLBACK_SOURCE}"
        obs, _stats, _flags = map_statement_row(
            row,
            kind="balance",
            instrument_id=thscode,
            published_at=resolved.published_at,
            source_id=HT_SOURCE,
            quality_status=qstat,
            published_at_source=resolved.source,
            revision_id=rev,
        )
        # Keep only total_equity for peer panel (plus MI if HT ever maps it — it doesn't).
        out.extend([o for o in obs if o.field_name == "total_equity"])
    diag.te_obs = len(out)
    return out


def _load_bank_f10_for_ticker(
    thscode: str,
    *,
    fund_db: Path,
    prefer_local: bool,
    diag: TickerPathDiag,
    max_annual: int = 12,
) -> list[FinancialObservation]:
    """EM companyType=3 OEI/MI/… Local-only unless refresh; never invent OEI.

    ``max_annual`` caps REST FY count (R4 peers default 12; R5 subject hist may raise).
    """
    _ensure_tables(fund_db)
    n = em_store.count_bank_f10(thscode, db_path=fund_db) if fund_db.is_file() else 0
    balance_rows: list[dict] = []
    income_rows: list[dict] = []
    path = "unset"

    if prefer_local:
        if n > 0:
            balance_rows = em_store.read_bank_f10(thscode, statement="zcfzb", db_path=fund_db)
            income_rows = em_store.read_bank_f10(thscode, statement="lrb", db_path=fund_db)
            path = "local"
        else:
            path = "local_miss_no_rest"
            diag.bank_f10_path = path
            diag.notes.append("BANK_F10_LOCAL_MISS")
            return []
    else:
        try:
            bundle = em_client.fetch_bank_f10_bundle(
                thscode, company_type=3, max_annual=int(max_annual),
            )
            em_store.upsert_bank_f10(
                thscode, statement="zcfzb", rows=bundle.get("balance") or [], db_path=fund_db,
            )
            em_store.upsert_bank_f10(
                thscode, statement="lrb", rows=bundle.get("income") or [], db_path=fund_db,
            )
            balance_rows = em_store.read_bank_f10(thscode, statement="zcfzb", db_path=fund_db)
            income_rows = em_store.read_bank_f10(thscode, statement="lrb", db_path=fund_db)
            path = "rest_upsert"
            diag.rest_calls += 1
        except Exception as e:  # noqa: BLE001
            if n > 0:
                balance_rows = em_store.read_bank_f10(thscode, statement="zcfzb", db_path=fund_db)
                income_rows = em_store.read_bank_f10(thscode, statement="lrb", db_path=fund_db)
                path = f"rest_failed_local:{type(e).__name__}"
                diag.notes.append(f"BANK_F10_REST_FAIL_LOCAL:{type(e).__name__}")
            else:
                path = f"rest_failed_empty:{type(e).__name__}"
                diag.errors.append(f"BANK_F10_REST:{type(e).__name__}")
                diag.bank_f10_path = path
                return []

    obs, _stats = map_bank_f10_rows(
        balance_rows=balance_rows,
        income_rows=income_rows,
        instrument_id=thscode,
        source_id=BANK_F10_SOURCE,
    )
    diag.bank_f10_path = path
    diag.bank_f10_obs = len(obs)
    return obs


def _load_equity_shares(
    thscode: str,
    *,
    fund_db: Path,
    prefer_local: bool,
    market: list[MarketObservation],
    diag: TickerPathDiag,
) -> list[MarketObservation]:
    """Stamp shares_outstanding from EM equity; local-only unless refresh."""
    _ensure_tables(fund_db)
    n = em_store.count_equity(thscode, db_path=fund_db) if fund_db.is_file() else 0
    rows: list[dict] = []
    path = "unset"

    if prefer_local:
        if n > 0:
            rows = em_store.read_equity(thscode, db_path=fund_db)
            path = "local"
        else:
            path = "local_miss_no_rest"
            diag.equity_path = path
            diag.notes.append("EQUITY_LOCAL_MISS")
            return market
    else:
        try:
            code = em_client.security_code_from_thscode(thscode)
            raw = em_client.fetch_datacenter_all(
                "RPT_F10_EH_EQUITY",
                filter_=f'(SECURITY_CODE="{code}")',
                sort_columns="NOTICE_DATE",
                referer="https://data.eastmoney.com/",
            )
            em_store.upsert_equity(thscode, raw, db_path=fund_db)
            rows = em_store.read_equity(thscode, db_path=fund_db)
            path = "rest_upsert"
            diag.rest_calls += 1
        except Exception as e:  # noqa: BLE001
            if n > 0:
                rows = em_store.read_equity(thscode, db_path=fund_db)
                path = f"rest_failed_local:{type(e).__name__}"
            else:
                path = f"rest_failed_empty:{type(e).__name__}"
                diag.errors.append(f"EQUITY_REST:{type(e).__name__}")
                diag.equity_path = path
                return market

    timeline = equity_share_timeline(rows)
    stamped = apply_shares_to_market(market, timeline)
    diag.equity_path = path
    diag.equity_rows = len(rows)
    return stamped


def _load_prices_for_ticker(
    thscode: str,
    *,
    market_db: Path,
    prefer_local: bool,
    start: date | None,
    end: date | None,
    diag: TickerPathDiag,
) -> list[MarketObservation]:
    if not market_db.is_file():
        diag.prices_path = "market_db_missing"
        diag.errors.append("MARKET_DB_MISSING")
        return []
    try:
        bars = read_raw_bars(thscode, start=start, end=end, db_path=market_db)
    except Exception as e:  # noqa: BLE001
        diag.prices_path = f"local_error:{type(e).__name__}"
        diag.errors.append(f"PRICES:{type(e).__name__}")
        return []
    if bars:
        diag.prices_path = "local"
        market = bars_to_market_obs(bars, instrument_id=thscode, shares_outstanding=None)
        diag.market_bars = len(market)
        return market
    if prefer_local:
        diag.prices_path = "local_miss_no_rest"
        diag.notes.append("PRICES_LOCAL_MISS")
        return []
    # Refresh: Recipe E via lab prices.
    try:
        from vms.providers.hithink.lab import load_lab_modules
        from vms.providers.hithink.prices import recipe_e_ensure_prices

        labs = load_lab_modules()
        p_end = end or date.today()
        p_start = start or date(p_end.year - 10, 1, 1)
        pdiag = recipe_e_ensure_prices(
            thscode, start=p_start, end=p_end, prefer_local=False, lab_prices=labs["lib_prices"],
        )
        bars = pdiag.get("bars") or []
        diag.prices_path = "rest_upsert"
        diag.rest_calls += 1
        market = bars_to_market_obs(bars, instrument_id=thscode, shares_outstanding=None)
        diag.market_bars = len(market)
        return market
    except Exception as e:  # noqa: BLE001
        diag.prices_path = f"rest_failed_empty:{type(e).__name__}"
        diag.errors.append(f"PRICES_REST:{type(e).__name__}")
        return []


def _load_industry_for_ticker(
    thscode: str,
    *,
    fund_db: Path,
    prefer_local: bool,
    diag: TickerPathDiag,
) -> InstrumentClassification | None:
    _ensure_tables(fund_db)
    local = em_store.read_industry(thscode, db_path=fund_db) if fund_db.is_file() else None
    parsed = local
    path = "unset"

    if prefer_local:
        if local and local.get("sw_l1_proxy"):
            path = "local"
        else:
            diag.industry_path = "local_miss_no_rest"
            return None
    else:
        try:
            body = em_client.fetch_company_survey(thscode)
            parsed = parse_company_survey(body)
            em_store.upsert_industry(thscode, parsed, db_path=fund_db)
            parsed = em_store.read_industry(thscode, db_path=fund_db)
            path = "rest_upsert"
            diag.rest_calls += 1
        except Exception as e:  # noqa: BLE001
            if local:
                parsed = local
                path = f"rest_failed_local:{type(e).__name__}"
            else:
                diag.industry_path = f"rest_failed_empty:{type(e).__name__}"
                return None

    if not parsed:
        diag.industry_path = path
        return None
    p = {
        "sw_l1_proxy": parsed.get("sw_l1_proxy"),
        "listing_date": parsed.get("listing_date"),
        "em_board": parsed.get("em_board"),
        "csrc_industry": parsed.get("csrc_industry"),
        "map_reason": parsed.get("map_reason"),
    }
    if p["listing_date"] and not hasattr(p["listing_date"], "isoformat"):
        try:
            p["listing_date"] = date.fromisoformat(str(p["listing_date"])[:10])
        except ValueError:
            p["listing_date"] = None
    cls = to_classification(p, instrument_id=thscode)
    diag.industry_path = path
    diag.classified = cls is not None
    return cls


def build_fi_peer_panel(
    *,
    subject_instrument_id: str,
    as_of: datetime,
    classifications: Sequence[InstrumentClassification] | None = None,
    candidate_ids: Sequence[str] | None = None,
    use_lean_curated: bool = False,
    extra_candidates: Sequence[str] | None = None,
    prefer_local: bool = True,
    fund_db: Path | str | None = None,
    market_db: Path | str | None = None,
    allow_report_date_fallback: bool = True,
    statement_limit: int = 40,
    price_lookback_years: int = 10,
    include_subject: bool = False,
) -> FiPeerPanelReport:
    """Merge multi-instrument TE + bank_f10 OEI/MI + market/shares (+ SW) for R3 peers.

    ``prefer_local=True`` (default / no ``--refresh``): zero REST even on miss —
    missing surfaces as per-ticker path diag / later peer exclusion.
    ``prefer_local=False``: allow Recipe E / EM upsert; on fail use local fallback
    or leave empty (never invent OEI).

    Candidate discovery default is classifications-only (R13 /
    ``RIM-FI-PEER-UNIVERSE-v2``); pass ``use_lean_curated=True`` to union curated IDs.
    """
    aids = cite(
        "RIM-FI-PEER-PANEL-v1",
        "RIM-FI-PEER-UNIVERSE-v2",
        "RIM-COMMON-EQUITY-v1",
        "HITHINK-LOCAL-FIRST-v1",
        "EM-FI-F10-v1",
        "EM-SHARES-EQUITY-v1",
        "HITHINK-NO-VENDOR-QFQ-v1",
        "INDUSTRY-SW-L1-PROXY-EM-v1",
    )
    flags: list[str] = [
        "FI_PEER_PANEL_BUILDER",
        "NO_INDUSTRY_UNSUPPORTED_LIFT",
        "RELATIVE_PRICING_ONLY",
    ]
    if prefer_local:
        flags.append("PANEL_PREFER_LOCAL")
    else:
        flags.append("PANEL_REFRESH_ALLOWED")

    fdb = Path(fund_db) if fund_db else fund_db_path()
    mdb = Path(market_db) if market_db else market_db_path()

    if candidate_ids is not None:
        candidates = sorted({str(x).strip() for x in candidate_ids if str(x).strip()})
        if not include_subject:
            candidates = [c for c in candidates if c != subject_instrument_id]
    else:
        candidates = discover_bank_candidates(
            subject_instrument_id=subject_instrument_id,
            classifications=classifications,
            as_of=as_of,
            use_lean_curated=use_lean_curated,
            extra_candidates=extra_candidates,
            fund_db=fdb,
        )
        if include_subject and subject_instrument_id not in candidates:
            # rare; discovery drops subject
            pass

    if use_lean_curated:
        flags.append("LEAN_CURATED_CANDIDATES")
    else:
        flags.append("CLASSIFICATIONS_ONLY_CANDIDATES")

    p_end = as_of.date()
    p_start = date(p_end.year - int(price_lookback_years), 1, 1)

    financial: list[FinancialObservation] = []
    market: list[MarketObservation] = []
    cls_out: list[InstrumentClassification] = []
    ticker_diags: list[TickerPathDiag] = []
    rest_total = 0

    bank_label = deposit_taking_fi_sw_label()

    for pid in candidates:
        diag = TickerPathDiag(instrument_id=pid)
        te = _load_te_for_ticker(
            pid,
            fund_db=fdb,
            prefer_local=prefer_local,
            allow_report_date_fallback=allow_report_date_fallback,
            statement_limit=statement_limit,
            diag=diag,
        )
        f10 = _load_bank_f10_for_ticker(
            pid, fund_db=fdb, prefer_local=prefer_local, diag=diag,
        )
        # TE without OEI must remain distinguishable — do not invent OEI zeros.
        financial.extend(te)
        financial.extend(f10)

        mkt = _load_prices_for_ticker(
            pid,
            market_db=mdb,
            prefer_local=prefer_local,
            start=p_start,
            end=p_end,
            diag=diag,
        )
        mkt = _load_equity_shares(
            pid, fund_db=fdb, prefer_local=prefer_local, market=mkt, diag=diag,
        )
        market.extend(mkt)

        cls = _load_industry_for_ticker(
            pid, fund_db=fdb, prefer_local=prefer_local, diag=diag,
        )
        if cls is not None:
            # Panel is deposit-taking oriented; still record whatever SW we got
            # (R3 nonbank veto uses latest PIT). Prefer deposit-taking SW label membership.
            cls_out.append(cls)
            if bank_label and cls.industry != bank_label:
                diag.notes.append(f"NON_DEPOSIT_SW={cls.industry}")

        rest_total += diag.rest_calls
        ticker_diags.append(diag)

    if prefer_local and rest_total > 0:
        flags.append("PANEL_REST_UNEXPECTED")
    if not any(t.bank_f10_obs > 0 for t in ticker_diags):
        flags.append("PANEL_BANK_F10_EMPTY")
    if not any(t.te_obs > 0 for t in ticker_diags):
        flags.append("PANEL_TE_EMPTY")

    detail = (
        f"n_candidates={len(candidates)}; n_financial={len(financial)}; "
        f"n_market={len(market)}; rest_calls={rest_total}; prefer_local={prefer_local}"
    )
    return FiPeerPanelReport(
        subject_instrument_id=subject_instrument_id,
        as_of=as_of.isoformat(),
        candidate_ids=list(candidates),
        financial=financial,
        market=market,
        classifications=cls_out,
        ticker_diagnostics=ticker_diags,
        flags=sorted(set(flags)),
        assumption_ids=aids,
        rest_calls=rest_total,
        detail=detail,
    )


def lean_curated_peer_ids(subject_instrument_id: str) -> list[str]:
    """Lean curated deposit-taking IDs excluding subject (test/helper)."""
    return sorted(i for i in LEAN_CURATED_DEPOSIT_TAKING_FI if i != subject_instrument_id)
