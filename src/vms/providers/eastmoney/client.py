"""Minimal Eastmoney datacenter + F10 HTTP client (no secrets)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
F10_SURVEY = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax"
UA = "Mozilla/5.0 (compatible; VMS-research/0.1; +local-offline-prefer)"
DEFAULT_SLEEP_S = 0.35


class EastmoneyHTTPError(RuntimeError):
    pass


def _request(url: str, *, referer: str, timeout: float = 30.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": referer, "Accept": "application/json,text/plain,*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise EastmoneyHTTPError(f"HTTP {e.code} for {url.split('?', 1)[0]}") from e
    except urllib.error.URLError as e:
        raise EastmoneyHTTPError(f"URL error for {url.split('?', 1)[0]}: {e.reason}") from e
    # F10 sometimes returns UTF-8 BOM
    text = raw.decode("utf-8-sig")
    return json.loads(text)


def fetch_datacenter(
    report_name: str,
    *,
    filter_: str,
    sort_columns: str,
    page_size: int = 500,
    page_number: int = 1,
    sleep_s: float = DEFAULT_SLEEP_S,
    referer: str = "https://data.eastmoney.com/",
) -> list[dict[str, Any]]:
    """Fetch one page of an Eastmoney datacenter report. Returns data rows (may be empty)."""
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "quoteColumns": "",
        "filter": filter_,
        "pageNumber": str(page_number),
        "pageSize": str(page_size),
        "sortTypes": "-1",
        "sortColumns": sort_columns,
        "source": "WEB",
        "client": "WEB",
    }
    url = DATACENTER + "?" + urllib.parse.urlencode(params)
    if sleep_s > 0:
        time.sleep(sleep_s)
    body = _request(url, referer=referer)
    code = body.get("code")
    if code not in (0, "0", None):
        # 9501 = report missing / bad sort — treat as empty for unknown reports
        msg = body.get("message") or body.get("msg") or str(code)
        if code in (9501, "9501"):
            return []
        raise EastmoneyHTTPError(f"datacenter {report_name}: code={code} message={msg}")
    result = body.get("result") or {}
    rows = result.get("data") or []
    return list(rows) if isinstance(rows, list) else []


def fetch_datacenter_all(
    report_name: str,
    *,
    filter_: str,
    sort_columns: str,
    page_size: int = 500,
    max_pages: int = 20,
    sleep_s: float = DEFAULT_SLEEP_S,
    referer: str = "https://data.eastmoney.com/",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        rows = fetch_datacenter(
            report_name, filter_=filter_, sort_columns=sort_columns,
            page_size=page_size, page_number=page, sleep_s=sleep_s, referer=referer,
        )
        out.extend(rows)
        if len(rows) < page_size:
            break
    return out


def security_code_from_thscode(thscode: str) -> str:
    return thscode.strip().upper().split(".", 1)[0]


def em_f10_code(thscode: str) -> str:
    """SH600519 / SZ000001 for F10 Ajax."""
    t = thscode.strip().upper()
    code, exch = t.split(".", 1)
    if exch in ("SH", "SS"):
        return f"SH{code}"
    if exch in ("SZ",):
        return f"SZ{code}"
    if exch in ("BJ",):
        return f"BJ{code}"
    raise ValueError(f"unsupported exchange in thscode={thscode!r}")


def fetch_company_survey(thscode: str, *, sleep_s: float = DEFAULT_SLEEP_S) -> dict[str, Any]:
    code = em_f10_code(thscode)
    url = f"{F10_SURVEY}?code={urllib.parse.quote(code)}"
    if sleep_s > 0:
        time.sleep(sleep_s)
    body = _request(url, referer="https://emweb.securities.eastmoney.com/")
    if not isinstance(body, dict):
        raise EastmoneyHTTPError("CompanySurveyAjax returned non-object")
    return body


F10_FIN_BASE = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis"


def fetch_bank_f10_dates(
    thscode: str,
    *,
    statement: str = "zcfzb",
    company_type: int = 3,
    report_date_type: int = 0,
    sleep_s: float = DEFAULT_SLEEP_S,
) -> list[dict[str, Any]]:
    """Available REPORT_DATEs for companyType=3 F10 statement (DateAjaxNew)."""
    code = em_f10_code(thscode)
    url = (
        f"{F10_FIN_BASE}/{statement}DateAjaxNew"
        f"?companyType={company_type}&reportDateType={report_date_type}"
        f"&code={urllib.parse.quote(code)}"
    )
    if sleep_s > 0:
        time.sleep(sleep_s)
    body = _request(url, referer=f"{F10_FIN_BASE}/Index?type=web&code={code}")
    if not isinstance(body, dict):
        raise EastmoneyHTTPError(f"{statement}DateAjaxNew returned non-object")
    rows = body.get("data") or []
    return list(rows) if isinstance(rows, list) else []


def fetch_bank_f10_statement(
    thscode: str,
    *,
    statement: str,
    dates: list[str],
    company_type: int = 3,
    report_date_type: int = 0,
    report_type: int = 1,
    sleep_s: float = DEFAULT_SLEEP_S,
) -> list[dict[str, Any]]:
    """Fetch companyType=3 F10 rows for given REPORT_DATE list (AjaxNew; dates required).

    ``statement``: zcfzb | lrb | xjllb. ``company_type=3`` = deposit-taking FI template.
    """
    if not dates:
        return []
    code = em_f10_code(thscode)
    dates_param = ",".join(dates)
    url = (
        f"{F10_FIN_BASE}/{statement}AjaxNew"
        f"?companyType={company_type}&reportDateType={report_date_type}"
        f"&reportType={report_type}&dates={urllib.parse.quote(dates_param)}"
        f"&code={urllib.parse.quote(code)}"
    )
    if sleep_s > 0:
        time.sleep(sleep_s)
    body = _request(url, referer=f"{F10_FIN_BASE}/Index?type=web&code={code}")
    if not isinstance(body, dict):
        raise EastmoneyHTTPError(f"{statement}AjaxNew returned non-object")
    rows = body.get("data") or []
    return list(rows) if isinstance(rows, list) else []


def fetch_bank_f10_bundle(
    thscode: str,
    *,
    company_type: int = 3,
    max_annual: int = 12,
    sleep_s: float = DEFAULT_SLEEP_S,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch annual companyType=3 F10 balance + income rows (up to max_annual FYs)."""
    date_rows = fetch_bank_f10_dates(
        thscode, statement="zcfzb", company_type=company_type, sleep_s=sleep_s,
    )
    annual: list[str] = []
    for r in date_rows:
        pe = str(r.get("REPORT_DATE") or "")[:10]
        if len(pe) == 10 and pe.endswith("-12-31"):
            annual.append(pe)
        if len(annual) >= max_annual:
            break
    if not annual:
        return {"balance": [], "income": [], "dates": []}
    bal: list[dict[str, Any]] = []
    inc: list[dict[str, Any]] = []
    chunk = 5
    for i in range(0, len(annual), chunk):
        part = annual[i : i + chunk]
        bal.extend(
            fetch_bank_f10_statement(
                thscode, statement="zcfzb", dates=part, company_type=company_type, sleep_s=sleep_s,
            )
        )
        inc.extend(
            fetch_bank_f10_statement(
                thscode, statement="lrb", dates=part, company_type=company_type, sleep_s=sleep_s,
            )
        )
    return {"balance": bal, "income": inc, "dates": annual}
