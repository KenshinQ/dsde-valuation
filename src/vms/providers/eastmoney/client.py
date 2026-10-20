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
