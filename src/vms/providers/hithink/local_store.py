"""Direct DuckDB reads for local-first ingest (no lab helpers / no requests required)."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from vms.providers.hithink.paths import duckdb_available, fund_db_path


def _con(db: Path):
    if not duckdb_available():
        raise RuntimeError("duckdb not installed; pip install 'dsde-valuation[hithink]'")
    return importlib.import_module("duckdb").connect(str(db), read_only=True)


def read_statements(
    thscode: str,
    kind: str,
    period: str,
    *,
    db_path: Path | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    table = {
        "income": "income_statements",
        "balance": "balance_sheets",
        "cashflow": "cashflow_statements",
    }[kind]
    path = Path(db_path) if db_path else fund_db_path()
    con = _con(path)
    try:
        df = con.execute(
            f"SELECT * FROM {table} WHERE thscode=? AND period=? ORDER BY period_end_ms DESC LIMIT ?",
            [thscode, period, limit],
        ).fetchdf()
        return df.to_dict(orient="records")
    finally:
        con.close()


def read_notices(thscode: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else fund_db_path()
    code = thscode.split(".", 1)[0]
    con = _con(path)
    try:
        df = con.execute(
            """
            SELECT * FROM em_earnings_notices
            WHERE security_code = ? OR thscode = ?
            ORDER BY report_date
            """,
            [code, thscode],
        ).fetchdf()
        return df.to_dict(orient="records")
    finally:
        con.close()


def count_statements(thscode: str, kind: str, period: str, *, db_path: Path | None = None) -> int:
    table = {
        "income": "income_statements",
        "balance": "balance_sheets",
        "cashflow": "cashflow_statements",
    }[kind]
    path = Path(db_path) if db_path else fund_db_path()
    con = _con(path)
    try:
        return int(con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE thscode=? AND period=?",
            [thscode, period],
        ).fetchone()[0])
    finally:
        con.close()
