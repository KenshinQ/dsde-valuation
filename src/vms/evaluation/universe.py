"""Universe loading: synthetic / FI lean / FI real / MATURE lean synthetic+real scaffold."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vms.data import synthetic as syn
from vms.data.io import LoadResult, load_directory, write_directory
from vms.schemas import (CorporateActionEvent, FinancialObservation, InstrumentClassification, MarketObservation,
                         QualityStatus, ReportingConvention, SourceDescriptor, UnitScale, Versioning,
                         format_validation_error)
from vms.seeding import stream_rng

TZ = ZoneInfo("Asia/Shanghai")

CF_FIELDS = frozenset({
    "cash_flow_from_operations", "capex", "acquisitions_net", "dividends_paid", "share_repurchases",
})


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UniverseInstrument(_M):
    instrument_id: str
    data_dir: str | None = None
    industry: str = "机械设备"
    scheme: str = "SW2021_L1"


class UniverseConfig(_M):
    universe_id: str
    data_label: str = "SYNTHETIC"
    instruments: list[UniverseInstrument] = Field(min_length=1)
    split_mode: str = "chronological"
    horizons_years: list[int] = Field(default_factory=lambda: [1])
    min_history_years: int = Field(default=3, ge=1)
    synthetic: dict[str, Any] | None = None
    bank_synthetic: dict[str, Any] | None = None
    fi_real: dict[str, Any] | None = None
    mature_synthetic: dict[str, Any] | None = None
    mature_real: dict[str, Any] | None = None
    forbid_random_splits: bool = True


def load_universe(path: str | Path) -> UniverseConfig:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return UniverseConfig.model_validate(data)
    except ValidationError as e:
        raise ValueError(format_validation_error(e, str(path))) from None


def _pub(pe: date) -> datetime:
    return datetime(pe.year + 1, 4, 20, 18, 0, tzinfo=TZ)


def _obs(iid: str, pe: date, stype: str, name: str, value: float, pub: datetime) -> FinancialObservation:
    return FinancialObservation(
        instrument_id=iid, period_end=pe, published_at=pub, ingested_at=pub + timedelta(days=1),
        statement_type=stype, field_name=name, value=float(value), currency="CNY",
        unit_scale=UnitScale.UNIT, source_id=syn.SYNTHETIC_SOURCE, revision_id="r0",
        quality_status=QualityStatus.OBSERVED)


def generate_eval_panel(*, seed: int, n_instruments: int = 2, start_year: int = 2015,
                        n_years: int = 9) -> dict[str, LoadResult]:
    """Multi-name annual synthetic panel for walk-forward (labeled SYNTHETIC, FULL_HISTORY)."""
    out: dict[str, LoadResult] = {}
    src = SourceDescriptor(
        source_id=syn.SYNTHETIC_SOURCE, reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
        versioning=Versioning.FULL_HISTORY, description="SYNTHETIC Phase-11 eval panel — not real data")
    for i in range(n_instruments):
        iid = f"SYN{i:06d}.SZ"
        rng = stream_rng(seed + i, f"eval_panel:{iid}")
        fin: list[FinancialObservation] = []
        rev = 100_000.0 * (1 + 0.1 * i)
        equity = 500_000.0
        debt = 80_000.0
        shares = 100_000_000.0
        for y in range(start_year, start_year + n_years):
            pe = date(y, 12, 31)
            pub = _pub(pe)
            g = float(np.clip(rng.normal(0.06, 0.08), -0.3, 0.4))
            rev *= 1 + g
            gm = float(np.clip(rng.normal(0.30, 0.03), 0.1, 0.6))
            ebit = rev * float(np.clip(rng.normal(0.10, 0.02), 0.02, 0.25))
            interest = debt * 0.04
            pretax = ebit - interest
            tax = 0.25 * max(pretax, 0.0)
            ni = (pretax - tax) * 0.95
            da = rev * 0.04
            capex = rev * 0.05
            cfo = ni + da
            flows = {
                "revenue": rev, "cost_of_revenue": rev * (1 - gm), "gross_profit": rev * gm,
                "operating_expenses": rev * gm - ebit, "ebit": ebit, "interest_expense": interest,
                "tax_expense": tax, "parent_net_income": ni, "depreciation_amortization": da,
                "capex": capex, "acquisitions_net": 0.0, "dividends_paid": ni * 0.3,
                "share_repurchases": 0.0, "cash_flow_from_operations": cfo,
                "non_recurring_items_pretax": 0.0,
            }
            for name, val in flows.items():
                st = "cash_flow" if name in CF_FIELDS else "income"
                fin.append(_obs(iid, pe, st, name, val, pub))
            equity = equity + ni - flows["dividends_paid"]
            debt = rev * 0.4
            stocks = {
                "cash": rev * 0.2, "interest_bearing_debt": debt, "accounts_receivable": rev * 0.15,
                "inventory": rev * 0.12, "accounts_payable": rev * 0.1,
                "total_liabilities": debt + rev * 0.3, "total_equity": equity,
                "total_assets": debt + rev * 0.3 + equity,
            }
            for name, val in stocks.items():
                fin.append(_obs(iid, pe, "balance_sheet", name, val, pub))
        mkt: list[MarketObservation] = []
        price = 10.0 + i
        for y in range(start_year, start_year + n_years + 1):
            for month in range(1, 13):
                if y == start_year + n_years and month > 6:
                    break
                d = date(y, month, calendar.monthrange(y, month)[1])
                price *= float(np.exp(rng.normal(0.005, 0.06)))
                mkt.append(MarketObservation(
                    instrument_id=iid, timestamp=datetime.combine(d, time(15, 0), TZ),
                    raw_close=round(price, 2), adjusted_close=round(price, 4),
                    shares_outstanding=shares, corporate_action_version="none", currency="CNY",
                    source_id=syn.SYNTHETIC_SOURCE))
        actions = [
            CorporateActionEvent(
                action_id=f"{iid}-DIV1", instrument_id=iid, action_type="cash_dividend",
                announced_at=datetime(start_year + 3, 5, 1, 18, 0, tzinfo=TZ),
                ex_date=date(start_year + 3, 6, 15), cash_per_share=0.2, currency="CNY",
                source_id=syn.SYNTHETIC_SOURCE, revision_id="r0"),
        ]
        cls = [InstrumentClassification(
            instrument_id=iid, scheme="SW2021_L1", industry="机械设备",
            published_at=datetime(start_year, 1, 1, 9, 0, tzinfo=TZ), source_id=syn.SYNTHETIC_SOURCE)]
        out[iid] = LoadResult(
            financial=fin, market=mkt, corporate_actions=actions, classifications=cls,
            sources={syn.SYNTHETIC_SOURCE: src}, corporate_actions_provided=True, sources_provided=True)
    return out


def materialize_universe(
    uni: UniverseConfig,
    *,
    work_dir: Path,
    prefer_local: bool = True,
) -> dict[str, LoadResult]:
    """Load per-instrument data dirs, or generate synthetic / FI / MATURE panels.

    ``prefer_local`` applies to ``fi_real`` / ``mature_real`` only. Synthetic
    paths never call REST. Explicit kind blocks are mutually exclusive.
    """
    import json

    kind_flags = {
        "synthetic": uni.synthetic is not None,
        "bank_synthetic": uni.bank_synthetic is not None,
        "fi_real": uni.fi_real is not None,
        "mature_synthetic": uni.mature_synthetic is not None,
        "mature_real": uni.mature_real is not None,
    }
    active = [k for k, on in kind_flags.items() if on]
    if len(active) > 1:
        raise ValueError(
            "universe cannot set multiple materialize kinds at once: "
            + ", ".join(active)
        )

    if uni.mature_real is not None:
        if "SYNTHETIC" in (uni.data_label or "").upper():
            raise ValueError(
                "mature_real universe data_label must not contain SYNTHETIC "
                f"(got {uni.data_label!r})"
            )
        work_dir.mkdir(parents=True, exist_ok=True)
        cfg = uni.mature_real or {}
        ids = list(cfg.get("instrument_ids") or [i.instrument_id for i in uni.instruments])
        loads: dict[str, LoadResult] = {}
        gaps: list[dict[str, Any]] = []
        for inst in uni.instruments:
            if ids and inst.instrument_id not in ids:
                continue
            if not inst.data_dir:
                gaps.append({
                    "instrument_id": inst.instrument_id,
                    "reason": "DATA_GAP_NO_DATA_DIR",
                    "note": "mature_real scaffold: missing data_dir; no invented panel",
                })
                continue
            res = load_directory(inst.data_dir)
            if not res.ok:
                gaps.append({
                    "instrument_id": inst.instrument_id,
                    "reason": "DATA_GAP_LOAD_FAILED",
                    "errors": list(res.errors),
                })
                continue
            loads[inst.instrument_id] = res
        if not prefer_local:
            gaps.append({
                "instrument_id": None,
                "reason": "REFRESH_NOOP_SCAFFOLD",
                "note": (
                    "mature_real --refresh has no Recipe-E panel yet; "
                    "left local/empty (no invent)"
                ),
            })
        diag = {
            "source_id": "mature_real_scaffold_v1",
            "prefer_local": prefer_local,
            "rest_calls": 0,
            "instrument_ids": ids,
            "n_loaded": len(loads),
            "gaps": gaps,
            "scaffold": bool(cfg.get("scaffold", True)),
            "as_of": cfg.get("as_of"),
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "assumption_ids": [
                "EVAL-MATURE-LEAN-REAL-OOS-v1",
                "HITHINK-LOCAL-FIRST-v1",
                "PIT-INCOMPLETE-v2",
                "PIT-ASSUMED-VENDOR-LATEST-v1",
            ],
            "flags": [
                "MATURE_REAL_SCAFFOLD",
                "NO_INVENT_PANEL",
                "CALIBRATION_INSUFFICIENT_DEFAULT",
            ],
            "notes": [
                "mature_real scaffold: missing local panel => DATA_GAP, not PASS",
            ],
        }
        (work_dir / "mature_real_materialize.json").write_text(
            json.dumps(diag, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return loads

    if uni.mature_synthetic is not None:
        cfg = uni.mature_synthetic or {}
        n = int(cfg.get("n_instruments", max(len(uni.instruments), 2)))
        panel = generate_eval_panel(
            seed=int(cfg.get("seed", 42)),
            n_instruments=n,
            start_year=int(cfg.get("start_year", 2015)),
            n_years=int(cfg.get("n_years", 9)),
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        for gid, load in panel.items():
            d = work_dir / "data" / gid
            write_directory(
                d,
                load.financial,
                load.market,
                load.corporate_actions,
                [load.sources[syn.SYNTHETIC_SOURCE]],
                fmt="csv",
                classifications=load.classifications,
            )
        (work_dir / "mature_synthetic_materialize.json").write_text(
            json.dumps(
                {
                    "source_id": "mature_synthetic_panel_v1",
                    "n_instruments": len(panel),
                    "instrument_ids": sorted(panel),
                    "seed": int(cfg.get("seed", 42)),
                    "data_label": uni.data_label,
                    "assumption_ids": ["EVAL-MATURE-LEAN-WF-v1"],
                    "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
                    "rest_calls": 0,
                },
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return panel

    if uni.fi_real is not None:
        if "SYNTHETIC" in (uni.data_label or "").upper():
            raise ValueError(
                "fi_real universe data_label must not contain SYNTHETIC "
                f"(got {uni.data_label!r})"
            )
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from vms.evaluation.fi_real_panel import materialize_fi_real_panel

        cfg = uni.fi_real or {}
        ids = list(cfg.get("instrument_ids") or [i.instrument_id for i in uni.instruments])
        tz = ZoneInfo("Asia/Shanghai")
        as_of_raw = cfg.get("as_of")
        if as_of_raw:
            as_of = datetime.fromisoformat(str(as_of_raw))
            if as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=tz)
        else:
            as_of = None
        panel, diag = materialize_fi_real_panel(
            ids,
            as_of=as_of,
            prefer_local=prefer_local,
            fund_db=cfg.get("fund_db"),
            market_db=cfg.get("market_db"),
            work_dir=work_dir,
            price_lookback_years=int(cfg.get("price_lookback_years", 20)),
            max_annual_f10=int(cfg.get("max_annual_f10", 20)),
            statement_limit=int(cfg.get("statement_limit", 40)),
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "fi_real_materialize.json").write_text(
            json.dumps(diag.as_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return panel
    if uni.bank_synthetic is not None:
        from vms.evaluation.bank_panel import generate_bank_eval_panel

        cfg = uni.bank_synthetic or {}
        ids = list(cfg.get("instrument_ids") or [i.instrument_id for i in uni.instruments])
        short = cfg.get("short_oei_ids")
        short_set = frozenset(short) if short is not None else None
        panel = generate_bank_eval_panel(
            seed=int(cfg.get("seed", 42)),
            instrument_ids=ids,
            start_year=int(cfg.get("start_year", 2008)),
            n_years=int(cfg.get("n_years", 16)),
            short_oei_ids=short_set,
        )
        for gid, load in panel.items():
            d = work_dir / "data" / gid
            write_directory(
                d,
                load.financial,
                load.market,
                load.corporate_actions,
                [load.sources[syn.SYNTHETIC_SOURCE]],
                fmt="csv",
                classifications=load.classifications,
            )
        return panel
    if uni.synthetic is not None or all(inst.data_dir is None for inst in uni.instruments):
        syn_cfg = uni.synthetic or {}
        n = int(syn_cfg.get("n_instruments", max(len(uni.instruments), 2)))
        panel = generate_eval_panel(
            seed=int(syn_cfg.get("seed", 42)), n_instruments=n,
            start_year=int(syn_cfg.get("start_year", 2015)), n_years=int(syn_cfg.get("n_years", 9)))
        for gid, load in panel.items():
            d = work_dir / "data" / gid
            write_directory(d, load.financial, load.market, load.corporate_actions,
                            [load.sources[syn.SYNTHETIC_SOURCE]], fmt="csv",
                            classifications=load.classifications)
        return panel
    loads: dict[str, LoadResult] = {}
    for inst in uni.instruments:
        if not inst.data_dir:
            raise ValueError(f"instrument {inst.instrument_id} missing data_dir and no synthetic block")
        res = load_directory(inst.data_dir)
        if not res.ok:
            raise ValueError(f"{inst.instrument_id}: " + "\n".join(res.errors))
        loads[inst.instrument_id] = res
    return loads
