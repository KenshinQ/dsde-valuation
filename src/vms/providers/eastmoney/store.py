"""Local-first DuckDB cache for Eastmoney enrichment tables (in fund DB)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vms.providers.hithink.paths import duckdb_available, fund_db_path

TZ = ZoneInfo("Asia/Shanghai")

SHAREBONUS_TABLE = "em_sharebonus"
EQUITY_TABLE = "em_equity_changes"
INDUSTRY_TABLE = "em_industry_profile"
BALANCE_LINES_TABLE = "em_balance_lines"
BANK_F10_TABLE = "em_bank_f10"


def _connect(db_path: Path, *, read_only: bool = False):
    import importlib
    duckdb = importlib.import_module("duckdb")
    return duckdb.connect(str(db_path), read_only=read_only)


def ensure_tables(db_path: Path | None = None) -> Path:
    if not duckdb_available():
        raise RuntimeError("duckdb required for EM enrichment cache")
    path = Path(db_path) if db_path else fund_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = _connect(path, read_only=False)
    try:
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {SHAREBONUS_TABLE} (
                thscode VARCHAR,
                security_code VARCHAR,
                report_date DATE,
                plan_notice_date DATE,
                notice_date DATE,
                ex_dividend_date DATE,
                pretax_bonus_rmb DOUBLE,
                bonus_it_ratio DOUBLE,
                bonus_ratio DOUBLE,
                transfer_it_ratio DOUBLE,
                it_ratio DOUBLE,
                total_shares DOUBLE,
                assign_progress VARCHAR,
                impl_plan_profile VARCHAR,
                raw_json VARCHAR,
                fetched_at TIMESTAMP,
                PRIMARY KEY (security_code, report_date)
            )
        """)
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {EQUITY_TABLE} (
                thscode VARCHAR,
                security_code VARCHAR,
                notice_date DATE,
                end_date DATE,
                total_shares DOUBLE,
                total_a_shares DOUBLE,
                change_reason VARCHAR,
                info_code VARCHAR,
                raw_json VARCHAR,
                fetched_at TIMESTAMP,
                PRIMARY KEY (security_code, notice_date, end_date)
            )
        """)
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {INDUSTRY_TABLE} (
                thscode VARCHAR PRIMARY KEY,
                security_code VARCHAR,
                em_board VARCHAR,
                csrc_industry VARCHAR,
                sw_l1_proxy VARCHAR,
                listing_date DATE,
                raw_json VARCHAR,
                fetched_at TIMESTAMP
            )
        """)

        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {BALANCE_LINES_TABLE} (
                thscode VARCHAR,
                security_code VARCHAR,
                report_date DATE,
                notice_date DATE,
                date_type_code VARCHAR,
                report_type_code VARCHAR,
                inventory DOUBLE,
                accounts_payable DOUBLE,
                accounts_receivable DOUBLE,
                monetary_funds DOUBLE,
                total_assets DOUBLE,
                total_liabilities DOUBLE,
                raw_json VARCHAR,
                fetched_at TIMESTAMP,
                PRIMARY KEY (security_code, report_date, date_type_code)
            )
        """)


        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {BANK_F10_TABLE} (
                thscode VARCHAR,
                security_code VARCHAR,
                statement VARCHAR,
                report_date DATE,
                notice_date DATE,
                raw_json VARCHAR,
                fetched_at TIMESTAMP,
                PRIMARY KEY (security_code, statement, report_date)
            )
        """)

    finally:
        con.close()
    return path


def count_sharebonus(thscode: str, db_path: Path | None = None) -> int:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return 0
    con = _connect(path, read_only=True)
    try:
        ensure = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [SHAREBONUS_TABLE],
        ).fetchone()
        if not ensure or ensure[0] == 0:
            # duckdb may use different catalog — try direct
            try:
                return int(con.execute(
                    f"SELECT COUNT(*) FROM {SHAREBONUS_TABLE} WHERE thscode = ?", [thscode]
                ).fetchone()[0])
            except Exception:
                return 0
        return int(con.execute(
            f"SELECT COUNT(*) FROM {SHAREBONUS_TABLE} WHERE thscode = ?", [thscode]
        ).fetchone()[0])
    except Exception:
        return 0
    finally:
        con.close()


def count_equity(thscode: str, db_path: Path | None = None) -> int:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return 0
    con = _connect(path, read_only=True)
    try:
        return int(con.execute(
            f"SELECT COUNT(*) FROM {EQUITY_TABLE} WHERE thscode = ?", [thscode]
        ).fetchone()[0])
    except Exception:
        return 0
    finally:
        con.close()


def read_sharebonus(thscode: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return []
    con = _connect(path, read_only=True)
    try:
        return con.execute(
            f"SELECT * FROM {SHAREBONUS_TABLE} WHERE thscode = ? ORDER BY report_date DESC",
            [thscode],
        ).fetchdf().to_dict(orient="records")
    except Exception:
        return []
    finally:
        con.close()


def read_equity(thscode: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return []
    con = _connect(path, read_only=True)
    try:
        return con.execute(
            f"SELECT * FROM {EQUITY_TABLE} WHERE thscode = ? ORDER BY notice_date ASC, end_date ASC",
            [thscode],
        ).fetchdf().to_dict(orient="records")
    except Exception:
        return []
    finally:
        con.close()


def read_industry(thscode: str, db_path: Path | None = None) -> dict[str, Any] | None:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return None
    con = _connect(path, read_only=True)
    try:
        rows = con.execute(
            f"SELECT * FROM {INDUSTRY_TABLE} WHERE thscode = ?", [thscode]
        ).fetchdf().to_dict(orient="records")
        return rows[0] if rows else None
    except Exception:
        return None
    finally:
        con.close()


def list_deposit_taking_fi_thscodes(db_path: Path | str | None = None) -> list[str]:
    """Local-first: thscodes in em_industry_profile with sw_l1_proxy == bank YAML label.

    Missing duckdb / DB file / table / empty label / query error → ``[]``.
    Never hits REST — discovery seed for classifications-only peer universe.
    """
    # Lazy import: industry → yaml only; no store cycle.
    from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label

    if not duckdb_available():
        return []
    label = deposit_taking_fi_sw_label()
    if not label:
        return []
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return []
    con = _connect(path, read_only=True)
    try:
        rows = con.execute(
            f"SELECT DISTINCT thscode FROM {INDUSTRY_TABLE} "
            f"WHERE sw_l1_proxy = ? AND thscode IS NOT NULL AND CAST(thscode AS VARCHAR) != '' "
            f"ORDER BY thscode",
            [label],
        ).fetchall()
        out: list[str] = []
        for r in rows or []:
            if not r or r[0] is None:
                continue
            s = str(r[0]).strip()
            if s:
                out.append(s)
        return out
    except Exception:
        return []
    finally:
        con.close()


def _parse_date(v: Any):
    if v is None or (isinstance(v, float) and str(v) == "nan"):
        return None
    if hasattr(v, "date") and not isinstance(v, datetime):
        # datetime.date
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s or s.lower() in ("none", "nan", "nat"):
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")[:10]).date()


def upsert_sharebonus(thscode: str, rows: list[dict[str, Any]], db_path: Path | None = None) -> int:
    path = ensure_tables(db_path)
    if not rows:
        return 0
    code = thscode.split(".", 1)[0]
    now = datetime.now(TZ).replace(tzinfo=None)
    con = _connect(path, read_only=False)
    try:
        for r in rows:
            con.execute(
                f"""
                INSERT OR REPLACE INTO {SHAREBONUS_TABLE}
                (thscode, security_code, report_date, plan_notice_date, notice_date, ex_dividend_date,
                 pretax_bonus_rmb, bonus_it_ratio, bonus_ratio, transfer_it_ratio, it_ratio,
                 total_shares, assign_progress, impl_plan_profile, raw_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    thscode,
                    str(r.get("SECURITY_CODE") or code),
                    _parse_date(r.get("REPORT_DATE")),
                    _parse_date(r.get("PLAN_NOTICE_DATE")),
                    _parse_date(r.get("NOTICE_DATE")),
                    _parse_date(r.get("EX_DIVIDEND_DATE")),
                    r.get("PRETAX_BONUS_RMB"),
                    r.get("BONUS_IT_RATIO"),
                    r.get("BONUS_RATIO"),
                    r.get("TRANSFER_IT_RATIO"),
                    r.get("IT_RATIO"),
                    r.get("TOTAL_SHARES"),
                    r.get("ASSIGN_PROGRESS"),
                    r.get("IMPL_PLAN_PROFILE"),
                    json.dumps(r, ensure_ascii=False, default=str),
                    now,
                ],
            )
        return len(rows)
    finally:
        con.close()


def upsert_equity(thscode: str, rows: list[dict[str, Any]], db_path: Path | None = None) -> int:
    path = ensure_tables(db_path)
    if not rows:
        return 0
    code = thscode.split(".", 1)[0]
    now = datetime.now(TZ).replace(tzinfo=None)
    con = _connect(path, read_only=False)
    try:
        n = 0
        for r in rows:
            nd = _parse_date(r.get("NOTICE_DATE"))
            ed = _parse_date(r.get("END_DATE"))
            if nd is None or ed is None:
                continue
            con.execute(
                f"""
                INSERT OR REPLACE INTO {EQUITY_TABLE}
                (thscode, security_code, notice_date, end_date, total_shares, total_a_shares,
                 change_reason, info_code, raw_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    thscode,
                    str(r.get("SECURITY_CODE") or code),
                    nd,
                    ed,
                    r.get("TOTAL_SHARES"),
                    r.get("TOTAL_A_SHARES"),
                    r.get("CHANGE_REASON"),
                    r.get("INFO_CODE"),
                    json.dumps(r, ensure_ascii=False, default=str),
                    now,
                ],
            )
            n += 1
        return n
    finally:
        con.close()


def upsert_industry(thscode: str, row: dict[str, Any], db_path: Path | None = None) -> None:
    path = ensure_tables(db_path)
    code = thscode.split(".", 1)[0]
    now = datetime.now(TZ).replace(tzinfo=None)
    con = _connect(path, read_only=False)
    try:
        con.execute(
            f"""
            INSERT OR REPLACE INTO {INDUSTRY_TABLE}
            (thscode, security_code, em_board, csrc_industry, sw_l1_proxy, listing_date, raw_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                thscode,
                code,
                row.get("em_board"),
                row.get("csrc_industry"),
                row.get("sw_l1_proxy"),
                row.get("listing_date"),
                json.dumps(row.get("raw") or {}, ensure_ascii=False, default=str),
                now,
            ],
        )
    finally:
        con.close()



def count_balance_lines(thscode: str, db_path: Path | None = None) -> int:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return 0
    con = _connect(path, read_only=True)
    try:
        return int(con.execute(
            f"SELECT COUNT(*) FROM {BALANCE_LINES_TABLE} WHERE thscode = ?", [thscode]
        ).fetchone()[0])
    except Exception:
        return 0
    finally:
        con.close()


def read_balance_lines(thscode: str, db_path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return []
    con = _connect(path, read_only=True)
    try:
        return con.execute(
            f"SELECT * FROM {BALANCE_LINES_TABLE} WHERE thscode = ? ORDER BY report_date DESC",
            [thscode],
        ).fetchdf().to_dict(orient="records")
    except Exception:
        return []
    finally:
        con.close()


def upsert_balance_lines(thscode: str, rows: list[dict[str, Any]], db_path: Path | None = None) -> int:
    path = ensure_tables(db_path)
    if not rows:
        return 0
    code = thscode.split(".", 1)[0]
    now = datetime.now(TZ).replace(tzinfo=None)
    con = _connect(path, read_only=False)
    try:
        n = 0
        for r in rows:
            rd = _parse_date(r.get("REPORT_DATE"))
            if rd is None:
                continue
            dtc = str(r.get("DATE_TYPE_CODE") or "")
            con.execute(
                f"""
                INSERT OR REPLACE INTO {BALANCE_LINES_TABLE}
                (thscode, security_code, report_date, notice_date, date_type_code, report_type_code,
                 inventory, accounts_payable, accounts_receivable, monetary_funds,
                 total_assets, total_liabilities, raw_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    thscode,
                    str(r.get("SECURITY_CODE") or code),
                    rd,
                    _parse_date(r.get("NOTICE_DATE")),
                    dtc,
                    str(r.get("REPORT_TYPE_CODE") or ""),
                    r.get("INVENTORY"),
                    r.get("ACCOUNTS_PAYABLE"),
                    r.get("ACCOUNTS_RECE"),
                    r.get("MONETARYFUNDS"),
                    r.get("TOTAL_ASSETS"),
                    r.get("TOTAL_LIABILITIES"),
                    json.dumps(r, ensure_ascii=False, default=str),
                    now,
                ],
            )
            n += 1
        return n
    finally:
        con.close()



def count_bank_f10(thscode: str, db_path: Path | None = None) -> int:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return 0
    con = _connect(path, read_only=True)
    try:
        return int(con.execute(
            f"SELECT COUNT(*) FROM {BANK_F10_TABLE} WHERE thscode = ?", [thscode]
        ).fetchone()[0])
    except Exception:
        return 0
    finally:
        con.close()


def read_bank_f10(
    thscode: str, *, statement: str, db_path: Path | None = None,
) -> list[dict[str, Any]]:
    path = Path(db_path) if db_path else fund_db_path()
    if not path.is_file():
        return []
    con = _connect(path, read_only=True)
    try:
        rows = con.execute(
            f"SELECT raw_json FROM {BANK_F10_TABLE} WHERE thscode = ? AND statement = ? "
            f"ORDER BY report_date DESC",
            [thscode, statement],
        ).fetchall()
        out: list[dict[str, Any]] = []
        for (raw,) in rows:
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out
    except Exception:
        return []
    finally:
        con.close()


def upsert_bank_f10(
    thscode: str,
    *,
    statement: str,
    rows: list[dict[str, Any]],
    db_path: Path | None = None,
) -> int:
    path = ensure_tables(db_path)
    if not rows:
        return 0
    code = thscode.split(".", 1)[0]
    now = datetime.now(TZ).replace(tzinfo=None)
    con = _connect(path, read_only=False)
    try:
        n = 0
        for r in rows:
            rd = _parse_date(r.get("REPORT_DATE"))
            if rd is None:
                continue
            con.execute(
                f"""
                INSERT OR REPLACE INTO {BANK_F10_TABLE}
                (thscode, security_code, statement, report_date, notice_date, raw_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    thscode,
                    str(r.get("SECURITY_CODE") or code),
                    statement,
                    rd,
                    _parse_date(r.get("NOTICE_DATE")),
                    json.dumps(r, ensure_ascii=False, default=str),
                    now,
                ],
            )
            n += 1
        return n
    finally:
        con.close()
