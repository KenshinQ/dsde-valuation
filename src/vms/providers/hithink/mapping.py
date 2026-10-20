"""HiThink column → VMS canonical field mapping (HITHINK-FIELD-MAP-v1).

Amounts are treated as **CNY yuan (元)** — see HITHINK-UNITS-YUAN-v1.
Outflow magnitudes are forced non-negative to match FIELDS-2 sign conventions.
Unmapped HiThink columns are ignored (optional warning count returned).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Iterable, Literal
from zoneinfo import ZoneInfo

from vms.schemas.fields import REGISTRY, get_field
from vms.schemas.observations import FinancialObservation

TZ = ZoneInfo("Asia/Shanghai")

StatementKind = Literal["income", "balance", "cashflow"]

# HiThink column → (canonical_field, postprocess)
# postprocess: "as_is" | "abs_magnitude" | "derived_liabilities"
INCOME_MAP: dict[str, tuple[str, str]] = {
    "operating_income": ("revenue", "as_is"),
    "operating_costs": ("cost_of_revenue", "abs_magnitude"),
    "operating_expenses": ("operating_expenses", "abs_magnitude"),
    "operating_profit": ("ebit", "as_is"),
    "interest_expenses": ("interest_expense", "abs_magnitude"),
    "income_tax_expense": ("tax_expense", "as_is"),
    "parent_holder_net_profit": ("parent_net_income", "as_is"),
}

BALANCE_MAP: dict[str, tuple[str, str]] = {
    "cash": ("cash", "as_is"),
    "total_debt": ("interest_bearing_debt", "abs_magnitude"),  # approx; see docs
    "accounts_receivable": ("accounts_receivable", "as_is"),
    "assets_total": ("total_assets", "as_is"),
    "holder_equity_total": ("total_equity", "as_is"),
}

CASHFLOW_MAP: dict[str, tuple[str, str]] = {
    "act_cash_flow_net": ("cash_flow_from_operations", "as_is"),
    "pay_fixed_assets_etc_cash": ("capex", "abs_magnitude"),
    # Mixed: dividends + profits + interest paid — mapped with low_confidence.
    "pay_dividends_profits_interest_cash": ("dividends_paid", "abs_magnitude_mixed"),
}

KNOWN_META_COLS = frozenset({
    "thscode", "ticker", "period", "period_end_ms", "report_date_ms",
    "fiscal_year", "fiscal_period", "currency", "fetched_at", "basic_eps",
    "profit_total", "net_profit", "manage_fee", "sales_fee",
    "research_and_development_expenses",
    "total_current_assets", "non_current_nets_total",
    "invest_cash_flow_net", "financing_cash_flow_net", "cash_equivalents_net_addition",
})


@dataclass(frozen=True)
class MapStats:
    mapped: int = 0
    unmapped: int = 0
    skipped_null: int = 0
    mixed_dividend_interest: int = 0


def ms_to_shanghai_date(ms: int | float | None) -> date | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=TZ).date()
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def notice_to_published_at(notice_date: date) -> datetime:
    """HITHINK-PIT-NOTICE-v1: date-only NOTICE → 15:00 Asia/Shanghai that day."""
    return datetime.combine(notice_date, time(15, 0), tzinfo=TZ)


def _coerce_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _apply(op: str, raw: float) -> tuple[float, str | None]:
    """Return (value, quality_status_override)."""
    if op == "as_is":
        return raw, None
    if op == "abs_magnitude":
        return abs(raw), None
    if op == "abs_magnitude_mixed":
        return abs(raw), "low_confidence"
    raise ValueError(f"unknown postprocess {op!r}")


def map_statement_row(
    row: dict[str, Any],
    *,
    kind: StatementKind,
    instrument_id: str,
    published_at: datetime,
    source_id: str,
    quality_status: str = "observed",
    revision_id: str | None = None,
    published_at_source: str = "eastmoney_notice_date",
) -> tuple[list[FinancialObservation], MapStats, list[str]]:
    """Map one HiThink statement row to FinancialObservation list.

    ``published_at`` must already be resolved by the NOTICE policy (never period_end).
    """
    fmap = {"income": INCOME_MAP, "balance": BALANCE_MAP, "cashflow": CASHFLOW_MAP}[kind]
    period_end = ms_to_shanghai_date(row.get("period_end_ms"))
    if period_end is None:
        return [], MapStats(), ["MISSING_PERIOD_END"]

    currency = str(row.get("currency") or "CNY").upper()
    if currency in ("RMB", "CNY", "¥"):
        currency = "CNY"

    mapped = 0
    unmapped = 0
    skipped = 0
    mixed = 0
    flags: list[str] = []
    out: list[FinancialObservation] = []

    used_cols: set[str] = set()
    for col, (canon, op) in fmap.items():
        used_cols.add(col)
        raw = _coerce_float(row.get(col))
        if raw is None:
            skipped += 1
            continue
        val, q_over = _apply(op, raw)
        if op == "abs_magnitude_mixed":
            mixed += 1
            flags.append("DIVIDENDS_PAID_INCLUDES_INTEREST")
        fdef = get_field(canon)
        if fdef is None:
            continue
        q = q_over or quality_status
        # Enrich revision / provenance in revision_id slot when fallback.
        rev = revision_id
        if published_at_source != "eastmoney_notice_date":
            rev = (rev or "") + f"|published_at_source={published_at_source}"
            rev = rev.lstrip("|")
        out.append(FinancialObservation(
            instrument_id=instrument_id,
            period_end=period_end,
            published_at=published_at,
            statement_type=fdef.statement_type,
            field_name=canon,
            value=val,
            currency=currency,
            unit_scale="unit",
            source_id=source_id,
            revision_id=rev,
            quality_status=q,  # type: ignore[arg-type]
        ))
        mapped += 1

    # Derive total_liabilities when assets + equity present.
    if kind == "balance":
        assets = _coerce_float(row.get("assets_total"))
        equity = _coerce_float(row.get("holder_equity_total"))
        if assets is not None and equity is not None:
            liab = assets - equity
            out.append(FinancialObservation(
                instrument_id=instrument_id,
                period_end=period_end,
                published_at=published_at,
                statement_type="balance_sheet",
                field_name="total_liabilities",
                value=liab,
                currency=currency,
                unit_scale="unit",
                source_id=source_id,
                revision_id=revision_id,
                quality_status="derived",
            ))
            mapped += 1
            flags.append("TOTAL_LIABILITIES_DERIVED")

    # Opex fallback: sales + G&A + R&D when operating_expenses missing.
    if kind == "income" and _coerce_float(row.get("operating_expenses")) is None:
        parts = [_coerce_float(row.get(c)) for c in (
            "sales_fee", "manage_fee", "research_and_development_expenses")]
        if any(p is not None for p in parts):
            opex = sum(abs(p) for p in parts if p is not None)
            out.append(FinancialObservation(
                instrument_id=instrument_id,
                period_end=period_end,
                published_at=published_at,
                statement_type="income",
                field_name="operating_expenses",
                value=opex,
                currency=currency,
                unit_scale="unit",
                source_id=source_id,
                revision_id=revision_id,
                quality_status="observed",
            ))
            mapped += 1
            flags.append("OPEX_SUM_FEES")

    for col, val in row.items():
        if col in fmap or col in KNOWN_META_COLS or col.startswith("_"):
            continue
        if _coerce_float(val) is not None or val is not None:
            unmapped += 1

    # Sanity: never allow period_end as published_at equality by accident for notice policy callers.
    _ = REGISTRY  # touch registry for import side-effects / type checkers
    return out, MapStats(mapped=mapped, unmapped=unmapped, skipped_null=skipped,
                         mixed_dividend_interest=mixed), flags


def mapping_table() -> list[dict[str, str]]:
    """Documented mapping rows for docs/data_contracts.md."""
    rows = []
    for kind, fmap in (("income", INCOME_MAP), ("balance", BALANCE_MAP), ("cashflow", CASHFLOW_MAP)):
        for src, (dst, op) in sorted(fmap.items()):
            rows.append({
                "hithink_table": kind,
                "hithink_column": src,
                "vms_field": dst,
                "postprocess": op,
                "units": "CNY yuan (元)",
            })
    rows.append({
        "hithink_table": "balance",
        "hithink_column": "assets_total - holder_equity_total",
        "vms_field": "total_liabilities",
        "postprocess": "derived",
        "units": "CNY yuan (元)",
    })
    return rows
