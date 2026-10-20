"""Load canonical observations from CSV with row-level actionable errors.

Phase 0: schema validation only. PIT filtering, de-duplication, restatement
handling and integrity gates are Phase 1 and are NOT performed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import pandas as pd
from pydantic import BaseModel, ValidationError

from vms.schemas import FinancialObservation, MarketObservation, format_validation_error

FINANCIAL_FILE = "financial_observations.csv"
MARKET_FILE = "market_observations.csv"

M = TypeVar("M", bound=BaseModel)


@dataclass
class LoadResult:
    financial: list[FinancialObservation] = field(default_factory=list)
    market: list[MarketObservation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _clean(v):  # noqa: ANN001
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def _load_csv(path: Path, model: type[M], errors: list[str]) -> list[M]:
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as e:  # pragma: no cover - pandas parse errors vary
        errors.append(f"{path}: cannot parse CSV: {e}")
        return []
    expected = set(model.model_fields)
    required = {n for n, f in model.model_fields.items() if f.is_required()}
    cols = set(df.columns)
    if missing := required - cols:
        errors.append(f"{path}: missing required columns {sorted(missing)}")
        return []
    if unknown := cols - expected:
        errors.append(f"{path}: unknown columns {sorted(unknown)}; allowed {sorted(expected)}")
        return []
    out: list[M] = []
    for i, row in enumerate(df.to_dict(orient="records"), start=2):  # line 1 is header
        try:
            out.append(model.model_validate({k: _clean(v) for k, v in row.items()}))
        except ValidationError as e:
            errors.append(format_validation_error(e, f"{path.name}:line {i}"))
    return out


def load_directory(input_dir: str | Path) -> LoadResult:
    d = Path(input_dir)
    res = LoadResult()
    if not d.is_dir():
        res.errors.append(f"input directory not found: {d}")
        return res
    fin, mkt = d / FINANCIAL_FILE, d / MARKET_FILE
    if not fin.is_file():
        res.errors.append(f"{d}: required file '{FINANCIAL_FILE}' not found")
    else:
        res.financial = _load_csv(fin, FinancialObservation, res.errors)
    if mkt.is_file():
        res.market = _load_csv(mkt, MarketObservation, res.errors)
    else:
        res.errors.append(f"{d}: required file '{MARKET_FILE}' not found")
    return res


def write_directory(out_dir: str | Path, financial: list[FinancialObservation],
                    market: list[MarketObservation]) -> None:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([o.model_dump(mode="json") for o in financial],
                 columns=list(FinancialObservation.model_fields)).to_csv(d / FINANCIAL_FILE, index=False)
    pd.DataFrame([o.model_dump(mode="json") for o in market],
                 columns=list(MarketObservation.model_fields)).to_csv(d / MARKET_FILE, index=False)
