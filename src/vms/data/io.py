"""Ingest canonical-schema tables from CSV or Parquet (Phase 1).

Directory layout (one format per table; both present => error):
  financial_observations.{csv,parquet}   required
  market_observations.{csv,parquet}      required
  corporate_actions.{csv,parquet}        optional (absence is flagged by the quality gate)
  sources.yaml                           optional (absence => sources undeclared => PIT_INCOMPLETE)

No provider-specific adapters live here: inputs must already be in the canonical schema.
Rows failing schema validation are reported with file and line/row number.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
import yaml
from pydantic import BaseModel, ValidationError

from vms.schemas import (CorporateActionEvent, FinancialObservation, MarketObservation, SourceDescriptor,
                         format_validation_error)

FINANCIAL = "financial_observations"
MARKET = "market_observations"
CORPORATE_ACTIONS = "corporate_actions"
SOURCES_FILE = "sources.yaml"
FINANCIAL_FILE = f"{FINANCIAL}.csv"   # back-compat names for default CSV output
MARKET_FILE = f"{MARKET}.csv"
TABLES: dict[str, type[BaseModel]] = {FINANCIAL: FinancialObservation, MARKET: MarketObservation,
                                      CORPORATE_ACTIONS: CorporateActionEvent}
REQUIRED_TABLES = (FINANCIAL, MARKET)
_DATETIME_FIELDS = {"published_at", "ingested_at", "timestamp", "announced_at"}

M = TypeVar("M", bound=BaseModel)


@dataclass
class LoadResult:
    financial: list[FinancialObservation] = field(default_factory=list)
    market: list[MarketObservation] = field(default_factory=list)
    corporate_actions: list[CorporateActionEvent] = field(default_factory=list)
    sources: dict[str, SourceDescriptor] = field(default_factory=dict)
    corporate_actions_provided: bool = False
    sources_provided: bool = False
    files: dict[str, dict[str, Any]] = field(default_factory=dict)   # name -> {sha256, rows, format}
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


def _read(path: Path) -> pd.DataFrame:
    if path.suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.read_parquet(path)


def _load_table(path: Path, model: type[M], errors: list[str]) -> list[M]:
    try:
        df = _read(path)
    except Exception as e:  # noqa: BLE001 - surface any parser error to the user
        errors.append(f"{path}: cannot read {path.suffix[1:]}: {e}")
        return []
    expected = set(model.model_fields)
    required = {n for n, f in model.model_fields.items() if f.is_required()}
    cols = set(map(str, df.columns))
    if missing := required - cols:
        errors.append(f"{path}: missing required columns {sorted(missing)}")
        return []
    if unknown := cols - expected:
        errors.append(f"{path}: unknown columns {sorted(unknown)}; allowed {sorted(expected)}")
        return []
    out: list[M] = []
    offset = 2 if path.suffix == ".csv" else 0   # CSV: line numbers (header = line 1); Parquet: row index
    label = "line" if path.suffix == ".csv" else "row"
    for i, row in enumerate(df.to_dict(orient="records"), start=offset):
        try:
            out.append(model.model_validate({k: _clean(v) for k, v in row.items()}))
        except ValidationError as e:
            errors.append(format_validation_error(e, f"{path.name}:{label} {i}"))
    return out


def _find(d: Path, table: str, errors: list[str]) -> Path | None:
    found = [p for p in (d / f"{table}.csv", d / f"{table}.parquet") if p.is_file()]
    if len(found) > 1:
        errors.append(f"{d}: both {table}.csv and {table}.parquet exist; keep exactly one")
        return None
    return found[0] if found else None


def _load_sources(path: Path, errors: list[str]) -> dict[str, SourceDescriptor]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        errors.append(f"{path}: invalid YAML: {e}")
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        errors.append(f"{path}: expected a mapping with a 'sources' list")
        return {}
    out: dict[str, SourceDescriptor] = {}
    for i, item in enumerate(data["sources"]):
        try:
            sd = SourceDescriptor.model_validate(item)
        except ValidationError as e:
            errors.append(format_validation_error(e, f"{path.name}:sources[{i}]"))
            continue
        if sd.source_id in out:
            errors.append(f"{path.name}: duplicate source_id {sd.source_id!r}")
        out[sd.source_id] = sd
    return out


def load_directory(input_dir: str | Path) -> LoadResult:
    d = Path(input_dir)
    res = LoadResult()
    if not d.is_dir():
        res.errors.append(f"input directory not found: {d}")
        return res
    for table, model in TABLES.items():
        path = _find(d, table, res.errors)
        if path is None:
            if table in REQUIRED_TABLES and not any(table in e for e in res.errors):
                res.errors.append(f"{d}: required table '{table}' (.csv or .parquet) not found")
            continue
        rows = _load_table(path, model, res.errors)
        res.files[path.name] = {"sha256": _sha256(path), "rows": len(rows), "format": path.suffix[1:]}
        setattr(res, {FINANCIAL: "financial", MARKET: "market", CORPORATE_ACTIONS: "corporate_actions"}[table], rows)
        if table == CORPORATE_ACTIONS:
            res.corporate_actions_provided = True
    src = d / SOURCES_FILE
    if src.is_file():
        res.sources = _load_sources(src, res.errors)
        res.sources_provided = True
        res.files[SOURCES_FILE] = {"sha256": _sha256(src), "rows": len(res.sources), "format": "yaml"}
    return res


def _to_frame(models: list[BaseModel], model: type[BaseModel], fmt: str) -> pd.DataFrame:
    cols = list(model.model_fields)
    if fmt == "csv":
        return pd.DataFrame([m.model_dump(mode="json") for m in models], columns=cols)
    rows = []
    for m in models:
        r = m.model_dump(mode="python")
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = pd.Timestamp(v).tz_convert("UTC")
            elif isinstance(v, date):
                r[k] = pd.Timestamp(v)
            elif hasattr(v, "value"):  # enums
                r[k] = v.value
        rows.append(r)
    df = pd.DataFrame(rows, columns=cols)
    for c in cols:
        if c in _DATETIME_FIELDS:
            df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert("Asia/Shanghai")
        elif c in ("period_end", "ex_date"):
            df[c] = pd.to_datetime(df[c]).dt.date
    return df


def write_directory(out_dir: str | Path, financial: list[FinancialObservation], market: list[MarketObservation],
                    corporate_actions: list[CorporateActionEvent] | None = None,
                    sources: list[SourceDescriptor] | None = None, fmt: str = "csv") -> None:
    if fmt not in ("csv", "parquet"):
        raise ValueError(f"fmt must be 'csv' or 'parquet', got {fmt!r}")
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    tables = [(FINANCIAL, financial, FinancialObservation), (MARKET, market, MarketObservation)]
    if corporate_actions is not None:
        tables.append((CORPORATE_ACTIONS, corporate_actions, CorporateActionEvent))
    for name, models, model in tables:
        df = _to_frame(list(models), model, fmt)
        if fmt == "csv":
            df.to_csv(d / f"{name}.csv", index=False)
        else:
            df.to_parquet(d / f"{name}.parquet", index=False)
    if sources is not None:
        (d / SOURCES_FILE).write_text(yaml.safe_dump(
            {"sources": [s.model_dump(mode="json") for s in sources]}, sort_keys=False), encoding="utf-8")
