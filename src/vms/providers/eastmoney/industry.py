"""Industry from Eastmoney F10 CompanySurvey → SW2021_L1 proxy names.

True Shenwan L1 membership is not on public EM datacenter reports probed
(2026-10-20). Mapping table lives in config/em_industry_proxy.yaml
(INDUSTRY-SW-L1-PROXY-EM-v1). Reclassification history unavailable
(INDUSTRY-NO-RECLASS-HISTORY-v1).

Industry name strings must not be hardcoded here — tests forbid scattered
sector conditionals in Python sources (see test_profiles).
"""

from __future__ import annotations

from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from vms.schemas.observations import InstrumentClassification

TZ = ZoneInfo("Asia/Shanghai")
SOURCE_ID = "em_f10_industry"
def _resolve_proxy_yaml() -> Path:
    """Locate config/em_industry_proxy.yaml in editable checkout or installed tree.

    parents[4] from site-packages points at pythonX.Y/, not the repo — walk up.
    Override with env VMS_EM_INDUSTRY_PROXY.
    """
    import os
    env = os.environ.get("VMS_EM_INDUSTRY_PROXY")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "config" / "em_industry_proxy.yaml"
        if cand.is_file():
            return cand
    bundled = here.parent / "em_industry_proxy.yaml"
    if bundled.is_file():
        return bundled
    raise FileNotFoundError(
        "em_industry_proxy.yaml not found; set VMS_EM_INDUSTRY_PROXY or keep "
        "config/em_industry_proxy.yaml at the repo root"
    )


_DEFAULT_YAML = None  # resolved lazily


@lru_cache(maxsize=1)
def _proxy_table(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else _resolve_proxy_yaml()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid industry proxy yaml: {p}")
    return data


def _parse_listing(s: Any) -> date | None:
    if s is None:
        return None
    text = str(s).strip()
    if not text or text in ("--", "-", "None"):
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def map_to_sw_l1(em_board: str | None, csrc: str | None, *, table: dict[str, Any] | None = None) -> tuple[str | None, str]:
    """Return (sw_l1_name_or_None, reason). All labels come from YAML."""
    cfg = table or _proxy_table()
    blob = f"{em_board or ''}|{csrc or ''}"
    board_map: dict[str, str] = {str(k): str(v) for k, v in (cfg.get("board_to_sw") or {}).items()}
    bank_label = str(cfg.get("unsupported_bank_label") or "")
    nonbank_label = str(cfg.get("unsupported_nonbank_label") or "")

    for kw in cfg.get("keyword_bank") or []:
        if kw and kw in blob:
            return (bank_label or board_map.get(str(kw)) or str(kw)), f"keyword_bank:{kw}"
    for kw in cfg.get("keyword_nonbank") or []:
        if kw and kw in blob:
            return (nonbank_label or str(kw)), f"keyword_nonbank:{kw}"

    board = (em_board or "").strip()
    if board in board_map:
        return board_map[board], f"board_exact:{board}"
    for k, v in board_map.items():
        if k and k in board:
            return v, f"board_contains:{k}"
    csrc_s = (csrc or "").strip()
    for k, v in board_map.items():
        if k and k in csrc_s:
            return v, f"csrc_contains:{k}"
    if board:
        return board, "unmapped_em_board_passthrough"
    if csrc_s:
        return csrc_s.split("-")[-1], "unmapped_csrc_passthrough"
    return None, "no_industry_fields"


def parse_company_survey(body: dict[str, Any]) -> dict[str, Any]:
    jb = body.get("jbzl") or {}
    fx = body.get("fxxg") or {}
    em_board = jb.get("sshy") or None
    csrc = jb.get("sszjhhy") or None
    listing = _parse_listing(fx.get("ssrq"))
    sw, reason = map_to_sw_l1(em_board, csrc)
    return {
        "em_board": em_board,
        "csrc_industry": csrc,
        "sw_l1_proxy": sw,
        "listing_date": listing,
        "map_reason": reason,
        "raw": {"jbzl_sshy": em_board, "jbzl_sszjhhy": csrc, "fxxg_ssrq": fx.get("ssrq")},
    }


def to_classification(
    parsed: dict[str, Any],
    *,
    instrument_id: str,
    source_id: str = SOURCE_ID,
    as_of_fallback: date | None = None,
) -> InstrumentClassification | None:
    industry = parsed.get("sw_l1_proxy")
    if not industry:
        return None
    listing = parsed.get("listing_date")
    pub_date = listing or as_of_fallback
    if pub_date is None:
        pub_date = date(2000, 1, 1)
    published_at = datetime.combine(pub_date, time(15, 0), tzinfo=TZ)
    scheme = str((_proxy_table().get("scheme") or "SW2021_L1"))
    return InstrumentClassification(
        instrument_id=instrument_id,
        scheme=scheme,
        industry=str(industry),
        published_at=published_at,
        source_id=source_id,
    )
