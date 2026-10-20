"""Configurable paths for HiThink / marketdb / Eastmoney notice stores."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

DEFAULT_FUND_DB = Path("/workspace/data/hithink_fundamentals.duckdb")
DEFAULT_MARKET_DB = Path("/workspace/data/market.duckdb")
DEFAULT_LAB_LIB = Path("/workspace/data/hithink_fund")

SOURCE_ID = "hithink_em_notice"


def fund_db_path() -> Path:
    return Path(os.environ.get("HITHINK_FUND_DB_PATH", str(DEFAULT_FUND_DB)))


def market_db_path() -> Path:
    return Path(os.environ.get("MARKETDB_DB_PATH", str(DEFAULT_MARKET_DB)))


def lab_lib_path() -> Path:
    return Path(os.environ.get("HITHINK_FUND_LIB", str(DEFAULT_LAB_LIB)))


def duckdb_available() -> bool:
    """True if the optional duckdb package is installed (no static import)."""
    return importlib.util.find_spec("duckdb") is not None
