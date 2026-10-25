"""R7: materialize lean deposit-taking FI LoadResults from HiThink + EM (real OOS).

Uses ``fetch_bundle`` (statements + prices + EM enrich) then deepens own-hist
via ``build_subject_hist_depth`` / ``merge_subject_hist_into_load`` (R5).

Local-first: ``prefer_local=True`` (default / no CLI ``--refresh``) ⇒ zero REST
even on miss. ``prefer_local=False`` allows Recipe E / EM upsert; fail →
local/empty; never invent OEI. Does not replace the offline synthetic panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vms.assumptions import cite
from vms.data.io import LoadResult, write_directory
from vms.methods.rim.subject_hist_depth import (
    build_subject_hist_depth,
    merge_subject_hist_into_load,
)
from vms.providers.hithink.adapter import fetch_bundle
from vms.providers.hithink.paths import fund_db_path, market_db_path

TZ = ZoneInfo("Asia/Shanghai")
FI_REAL_SOURCE_ID = "fi_real_oos_panel_v1"
DEFAULT_AS_OF = datetime(2025, 6, 30, 15, 0, tzinfo=TZ)


def _count_rest(diag: Any, depth_rest: int, prefer_local: bool) -> int:
    """Tally REST attempts from fetch_bundle notes + subject-hist depth."""
    n = int(depth_rest)
    notes = list(getattr(diag, "rest_notes", None) or [])
    for note in notes:
        s = str(note).lower()
        if "recipe e" in s or "upsert" in s or "rest" in s:
            n += 1
    enr = getattr(diag, "enrichment", None) or {}
    if isinstance(enr, dict):
        for v in enr.values():
            if isinstance(v, dict) and str(v.get("path") or "").startswith("rest"):
                n += 1
    price = getattr(diag, "price_diag", None) or {}
    if isinstance(price, dict) and price.get("rest_used"):
        n += 1
    if prefer_local:
        # Path labels alone from prior upserts must not inflate; only live notes.
        # Recompute strictly from this-call rest_notes + depth.
        n = int(depth_rest) + sum(
            1
            for note in notes
            if ("recipe e" in str(note).lower() or "upsert" in str(note).lower())
        )
        if isinstance(price, dict) and price.get("rest_used"):
            n += 1
    return n


@dataclass
class FiRealMaterializeReport:
    """Diagnostics for one real-panel materialize pass."""

    instrument_ids: list[str]
    prefer_local: bool
    rest_calls: int
    as_of: str
    fund_db: str
    market_db: str
    ticker_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    assumption_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_ids": list(self.instrument_ids),
            "prefer_local": self.prefer_local,
            "rest_calls": self.rest_calls,
            "as_of": self.as_of,
            "fund_db": self.fund_db,
            "market_db": self.market_db,
            "ticker_diagnostics": list(self.ticker_diagnostics),
            "flags": list(self.flags),
            "assumption_ids": list(self.assumption_ids),
            "notes": list(self.notes),
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "no_invent_oei": True,
            "min_hist_pb_points_unchanged": True,
            "source_id": FI_REAL_SOURCE_ID,
        }


def materialize_fi_real_panel(
    instrument_ids: list[str],
    *,
    as_of: datetime | None = None,
    prefer_local: bool = True,
    fund_db: Path | str | None = None,
    market_db: Path | str | None = None,
    work_dir: Path | None = None,
    price_lookback_years: int = 20,
    max_annual_f10: int = 20,
    statement_limit: int = 40,
) -> tuple[dict[str, LoadResult], FiRealMaterializeReport]:
    """Load per-instrument HiThink statements + EM enrich, then deepen subject hist.

    Never routes through the synthetic deposit-taking panel. Never invents OEI.
    """
    aids = cite(
        "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1",
        "RIM-SUBJECT-HIST-DEPTH-v1",
        "HITHINK-LOCAL-FIRST-v1",
        "EM-FI-F10-v1",
        "EM-SHARES-EQUITY-v1",
        "HITHINK-NO-VENDOR-QFQ-v1",
        "INDUSTRY-SW-L1-PROXY-EM-v1",
        "PIT-INCOMPLETE-v1",
    )
    flags: list[str] = [
        "FI_REAL_OOS_PANEL",
        "NO_INDUSTRY_UNSUPPORTED_LIFT",
        "NO_INVENT_OEI",
        "MIN_HIST_PB_POINTS_UNCHANGED",
        "FORBID_DEFAULT_PB_CENTER_2",
    ]
    if prefer_local:
        flags.append("FI_REAL_PREFER_LOCAL")
    else:
        flags.append("FI_REAL_REFRESH_ALLOWED")

    ids = [str(x).strip() for x in instrument_ids if str(x).strip()]
    if not ids:
        raise ValueError("fi_real panel requires at least one instrument_id")

    as_of = as_of or DEFAULT_AS_OF
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=TZ)

    fdb = Path(fund_db) if fund_db else fund_db_path()
    mdb = Path(market_db) if market_db else market_db_path()

    loads: dict[str, LoadResult] = {}
    ticker_diags: list[dict[str, Any]] = []
    rest_total = 0
    notes: list[str] = []

    # When prefer_local, force min_local=0 so statement branch never REST-fills.
    min_local = 0 if prefer_local else 4

    for iid in ids:
        load, diag = fetch_bundle(
            iid,
            prefer_local=prefer_local,
            min_local=min_local,
            fund_db=fdb,
            market_db=mdb,
            statement_limit=statement_limit,
            include_prices=True,
        )
        depth = build_subject_hist_depth(
            instrument_id=iid,
            as_of=as_of,
            prefer_local=prefer_local,
            fund_db=fdb,
            market_db=mdb,
            statement_limit=statement_limit,
            price_lookback_years=price_lookback_years,
            max_annual_f10=max_annual_f10,
        )
        merged = merge_subject_hist_into_load(load, depth)
        rest_i = _count_rest(diag, depth.rest_calls, prefer_local)
        rest_total += rest_i

        ticker_diags.append(
            {
                "instrument_id": iid,
                "rest_calls": rest_i,
                "n_financial": len(merged.financial),
                "n_market": len(merged.market),
                "n_classifications": len(merged.classifications),
                "fetch_rest_notes": list(getattr(diag, "rest_notes", []) or []),
                "subject_hist_rest": int(depth.rest_calls),
                "subject_hist_detail": depth.detail,
                "enrichment_paths": {
                    k: (v.get("path") if isinstance(v, dict) else None)
                    for k, v in (getattr(diag, "enrichment", None) or {}).items()
                    if isinstance(v, dict)
                },
                "has_revenue": any(
                    o.field_name == "revenue" and o.period_end.month == 12
                    for o in merged.financial
                ),
            }
        )
        if not any(o.field_name == "revenue" for o in merged.financial):
            notes.append(f"NO_REVENUE:{iid}")
        if len(merged.market) == 0:
            notes.append(f"PRICES_EMPTY:{iid}")

        loads[iid] = merged

        if work_dir is not None:
            d = Path(work_dir) / "data" / iid
            write_directory(
                d,
                merged.financial,
                merged.market,
                merged.corporate_actions,
                list(merged.sources.values()),
                fmt="csv",
                classifications=merged.classifications,
            )

    if prefer_local and rest_total > 0:
        flags.append("FI_REAL_REST_UNEXPECTED")

    report = FiRealMaterializeReport(
        instrument_ids=ids,
        prefer_local=prefer_local,
        rest_calls=rest_total,
        as_of=as_of.isoformat(),
        fund_db=str(fdb),
        market_db=str(mdb),
        ticker_diagnostics=ticker_diags,
        flags=sorted(set(flags)),
        assumption_ids=aids,
        notes=notes,
    )
    return loads, report


__all__ = [
    "DEFAULT_AS_OF",
    "FI_REAL_SOURCE_ID",
    "FiRealMaterializeReport",
    "materialize_fi_real_panel",
]
