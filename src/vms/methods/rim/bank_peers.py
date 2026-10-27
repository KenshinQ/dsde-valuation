"""R3/R13: deposit-taking FI peer PIT universe for pb_common (RIM-FI-PEER-UNIVERSE-v2).

Builds PeerObservation rows for R2c without lifting industry.unsupported.
Candidate discovery SoT (default) = classifications plane only:
  local DuckDB em_industry_profile (sw_l1_proxy == deposit_taking_fi_sw_label())
  ∪ in-memory PIT InstrumentClassification matching the YAML bank label
  ∪ extra_candidates − subject.
Lean curated allowlist (LEAN_CURATED_DEPOSIT_TAKING_FI) is opt-in via
use_lean_curated=True (synthetic panel / calibrate-rim / tests). Empty plane →
empty peers + exclusion funnel (honest PEER_SCARCITY; no curated bootstrap).

pb_common = raw_close / ((TE − MI − OEI) / shares) with PIT gates on financial
published_at and market timestamp (NOTICE-aligned). Missing OEI ⇒ exclude with
canonical code MISSING_OTHER_EQUITY_INSTRUMENTS (never treat TE as common).

Ownership:
- Industry LABEL SoT: config/em_industry_proxy.yaml via deposit_taking_fi_sw_label()
  — never hardcode industry label strings in this module.
- Classifications plane: store scan + PIT classifications (R13 default).
- Lean curated IDs: instrument-ID allowlist kept for opt-in / eval metadata only.
  Latest PIT non-deposit-taking classification still vetoes a candidate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from vms.assumptions import cite
from vms.methods.rim.hist_pb import PEER_FIELD_PB_COMMON
from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label
from vms.schemas.observations import (
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
    PeerObservation,
    QualityStatus,
)

SOURCE_ID = "fi_peer_universe_v1"

# Exclusion codes: align peer funnel with subject bridge (rim/from_snapshot).
# Canonical = MISSING_OTHER_EQUITY_INSTRUMENTS; MISSING_OEI is a short alias only.
EXCLUSION_MISSING_OEI = "MISSING_OTHER_EQUITY_INSTRUMENTS"
EXCLUSION_CODE_ALIASES: dict[str, str] = {
    "MISSING_OEI": EXCLUSION_MISSING_OEI,
}

# Universe-level flags only (peer-level cflags must not land here).
_UNIVERSE_FLAG_SEED = (
    "FI_PEER_UNIVERSE_BUILDER",
    "RELATIVE_PRICING_ONLY",
    "NO_INDUSTRY_UNSUPPORTED_LIFT",
)


# Lean curated data plane (opt-in): major A-share deposit-taking FI tickers only.
# Ownership: instrument IDs live here; industry LABELS live in YAML
# (deposit_taking_fi_sw_label). Do not duplicate label strings beside this tuple.
# Default discovery is classifications-only (R13); curated unions only when
# use_lean_curated=True — see module docstring.
LEAN_CURATED_DEPOSIT_TAKING_FI: tuple[str, ...] = (
    "000001.SZ",
    "002142.SZ",
    "600000.SH",
    "600015.SH",
    "600016.SH",
    "600036.SH",
    "600919.SH",
    "600926.SH",
    "601009.SH",
    "601166.SH",
    "601169.SH",
    "601229.SH",
    "601288.SH",
    "601328.SH",
    "601398.SH",
    "601658.SH",
    "601818.SH",
    "601939.SH",
    "601988.SH",
    "601998.SH",
)


@dataclass(frozen=True)
class PeerExclusionRecord:
    peer_instrument_id: str
    reasons: list[str]
    detail: str = ""
    peer_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FiPeerUniverseReport:
    subject_instrument_id: str
    as_of: str
    peers: list[PeerObservation]
    excluded: list[PeerExclusionRecord]
    candidate_ids: list[str]
    flags: list[str]
    assumption_ids: list[str]
    funnel: dict[str, int] = field(default_factory=dict)
    peer_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""
    source_id: str = SOURCE_ID

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject_instrument_id": self.subject_instrument_id,
            "as_of": self.as_of,
            "n_peers": len(self.peers),
            "n_excluded": len(self.excluded),
            "candidate_ids": list(self.candidate_ids),
            "peers": [p.model_dump(mode="json") for p in self.peers],
            "excluded": [
                {
                    "peer_instrument_id": e.peer_instrument_id,
                    "reasons": list(e.reasons),
                    "detail": e.detail,
                    "peer_flags": list(e.peer_flags),
                }
                for e in self.excluded
            ],
            "funnel": dict(self.funnel),
            "flags": list(self.flags),
            "peer_diagnostics": list(self.peer_diagnostics),
            "assumption_ids": list(self.assumption_ids),
            "source_id": self.source_id,
            "detail": self.detail,
            "exclusion_code_aliases": dict(EXCLUSION_CODE_ALIASES),
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "peer_field": PEER_FIELD_PB_COMMON,
        }


def discover_bank_candidates(
    *,
    subject_instrument_id: str,
    classifications: Sequence[InstrumentClassification] | None = None,
    as_of: datetime,
    use_lean_curated: bool = False,
    extra_candidates: Sequence[str] | None = None,
    fund_db: Path | str | None = None,
) -> list[str]:
    """Classifications-plane candidates (default); curated only when use_lean_curated=True.

    Membership = store_ids (em_industry_profile sw_l1_proxy == YAML bank label)
    ∪ PIT classifications matching bank label ∪ extras [∪ curated if opt-in]
    − subject. Store miss / empty → no invent (local-first, zero REST).
    """
    from vms.providers.eastmoney.store import list_deposit_taking_fi_thscodes

    bank_label = deposit_taking_fi_sw_label()
    ids: set[str] = set()
    # Classifications plane seed: local fund DuckDB (always; empty-safe).
    ids.update(list_deposit_taking_fi_thscodes(fund_db))
    if use_lean_curated:
        ids.update(LEAN_CURATED_DEPOSIT_TAKING_FI)
    if extra_candidates:
        ids.update(str(x).strip() for x in extra_candidates if str(x).strip())
    for c in classifications or []:
        if c.published_at > as_of:
            continue
        if bank_label and c.industry == bank_label:
            ids.add(c.instrument_id)
    ids.discard(subject_instrument_id)
    return sorted(ids)


def _latest_pit_classification(
    classifications: Sequence[InstrumentClassification] | None,
    *,
    instrument_id: str,
    as_of: datetime,
) -> InstrumentClassification | None:
    """Latest classification row for instrument with published_at <= as_of."""
    best: InstrumentClassification | None = None
    for c in classifications or []:
        if c.instrument_id != instrument_id:
            continue
        if c.published_at > as_of:
            continue
        if best is None or c.published_at >= best.published_at:
            best = c
    return best


def subject_allows_auto_fi_peers(
    *,
    primary_profile: str | Any,
    instrument_id: str,
    as_of: datetime,
    classifications: Sequence[InstrumentClassification] | None = None,
) -> bool:
    """True iff latest PIT SW L1 label is deposit-taking FI (YAML via deposit_taking_fi_sw_label).

    R3 deposit-taking boundary: never short-circuit on ProfileLabel.FINANCIAL_INSTITUTION
    alone — non-deposit SW L1 subjects can still classify as FI but must NOT auto-build
    the deposit-taking peer universe. ``primary_profile`` is accepted for call-site
    stability and is not used for the allow decision.

    Honest missing-classification path: no usable latest PIT SW row (or empty YAML label)
    ⇒ False (skip auto; require SW). Do not invent deposit-taking membership from profile.
    """
    _ = primary_profile  # call-site compat; profile alone never grants auto FI peers
    bank_label = deposit_taking_fi_sw_label()
    if not bank_label:
        return False
    latest = _latest_pit_classification(
        classifications, instrument_id=instrument_id, as_of=as_of,
    )
    return latest is not None and latest.industry == bank_label


def _fy_field_at(
    fins: Sequence[FinancialObservation],
    *,
    instrument_id: str,
    field_name: str,
    year: int,
    as_of: datetime,
) -> tuple[float | None, datetime | None]:
    """Latest revision of field for FY-12-31 of year with published_at <= as_of."""
    pe = date(year, 12, 31)
    best_val: float | None = None
    best_pub: datetime | None = None
    for f in fins:
        if f.instrument_id != instrument_id:
            continue
        if f.field_name != field_name:
            continue
        if f.period_end != pe:
            continue
        if f.published_at > as_of:
            continue
        if f.value is None or not math.isfinite(float(f.value)):
            continue
        if best_pub is None or f.published_at >= best_pub:
            best_val = float(f.value)
            best_pub = f.published_at
    return best_val, best_pub


def _available_fy_years(
    fins: Sequence[FinancialObservation],
    *,
    instrument_id: str,
    as_of: datetime,
) -> list[int]:
    years: set[int] = set()
    for f in fins:
        if f.instrument_id != instrument_id:
            continue
        if f.period_end.month != 12 or f.period_end.day != 31:
            continue
        if f.published_at > as_of:
            continue
        years.add(f.period_end.year)
    return sorted(years, reverse=True)


def _spot_and_shares(
    mkts: Sequence[MarketObservation],
    *,
    instrument_id: str,
    as_of: datetime,
) -> tuple[float | None, float | None, datetime | None, list[str]]:
    flags: list[str] = []
    best_px: float | None = None
    best_sh: float | None = None
    best_ts: datetime | None = None
    for m in mkts:
        if m.instrument_id != instrument_id:
            continue
        if m.timestamp > as_of:
            continue
        px = float(m.raw_close)
        if not (math.isfinite(px) and px > 0):
            flags.append("SKIP_NONPOSITIVE_RAW_CLOSE")
            continue
        sh = m.shares_outstanding
        if best_ts is None or m.timestamp >= best_ts:
            best_px = px
            best_ts = m.timestamp
            if sh is not None and math.isfinite(float(sh)) and float(sh) > 0:
                best_sh = float(sh)
    # shares may lag on older bars — take latest positive shares_outstanding <= as_of
    if best_sh is None:
        for m in sorted(
            (x for x in mkts if x.instrument_id == instrument_id and x.timestamp <= as_of),
            key=lambda x: x.timestamp,
            reverse=True,
        ):
            sh = m.shares_outstanding
            if sh is not None and math.isfinite(float(sh)) and float(sh) > 0:
                best_sh = float(sh)
                break
    return best_px, best_sh, best_ts, flags


def compute_peer_pb_common(
    *,
    peer_instrument_id: str,
    as_of: datetime,
    financial: Sequence[FinancialObservation],
    market: Sequence[MarketObservation],
    zeros_explicit: bool = True,
) -> tuple[float | None, datetime | None, datetime | None, list[str], str]:
    """Return (pb, published_at, metric_timestamp, flags, detail_or_reason).

    On failure pb is None and detail holds the primary exclusion reason.
    """
    flags: list[str] = []
    years = _available_fy_years(financial, instrument_id=peer_instrument_id, as_of=as_of)
    if not years:
        return None, None, None, flags, "MISSING_FINANCIALS"

    chosen: dict[str, Any] | None = None
    for y in years:
        te, te_pub = _fy_field_at(
            financial, instrument_id=peer_instrument_id, field_name="total_equity", year=y, as_of=as_of,
        )
        if te is None or te_pub is None:
            continue
        oei, oei_pub = _fy_field_at(
            financial,
            instrument_id=peer_instrument_id,
            field_name="other_equity_instruments",
            year=y,
            as_of=as_of,
        )
        if oei is None or oei_pub is None:
            # Never treat TE as common — record and try older year only if we never find OEI
            continue
        mi, mi_pub = _fy_field_at(
            financial,
            instrument_id=peer_instrument_id,
            field_name="minority_interest",
            year=y,
            as_of=as_of,
        )
        if mi is None:
            if not zeros_explicit:
                continue
            mi = 0.0
            mi_pub = te_pub
            flags.append(f"MINORITY_EQUITY_ASSUMED_ZERO@{y}")
        common = float(te) - float(mi) - float(oei)
        if not (math.isfinite(common) and common > 0):
            flags.append(f"NONPOSITIVE_COMMON_EQUITY@{y}")
            continue
        pubs = [p for p in (te_pub, oei_pub, mi_pub) if p is not None]
        chosen = {
            "year": y,
            "te": float(te),
            "mi": float(mi),
            "oei": float(oei),
            "common": common,
            "published_at": max(pubs),
        }
        break

    if chosen is None:
        # Distinguish MISSING_OTHER_EQUITY_INSTRUMENTS (have TE somewhere) vs MISSING_TE
        any_te = False
        any_oei = False
        for y in years:
            te, _ = _fy_field_at(
                financial, instrument_id=peer_instrument_id, field_name="total_equity", year=y, as_of=as_of,
            )
            oei, _ = _fy_field_at(
                financial,
                instrument_id=peer_instrument_id,
                field_name="other_equity_instruments",
                year=y,
                as_of=as_of,
            )
            if te is not None:
                any_te = True
            if oei is not None:
                any_oei = True
        if any_te and not any_oei:
            return None, None, None, flags, EXCLUSION_MISSING_OEI
        if not any_te:
            return None, None, None, flags, "MISSING_TE"
        return None, None, None, flags, "MISSING_COMMON_EQUITY_COMPONENTS"

    px, shares, mts, pflags = _spot_and_shares(
        market, instrument_id=peer_instrument_id, as_of=as_of,
    )
    flags.extend(pflags)
    if px is None or mts is None:
        return None, chosen["published_at"], None, flags, "MISSING_RAW_CLOSE"
    if shares is None:
        return None, chosen["published_at"], mts, flags, "MISSING_SHARES"
    bps = float(chosen["common"]) / float(shares)
    if not (math.isfinite(bps) and bps > 0):
        return None, chosen["published_at"], mts, flags, "NONPOSITIVE_BPS"
    pb = float(px) / bps
    if not (math.isfinite(pb) and pb > 0):
        return None, chosen["published_at"], mts, flags, "NONPOSITIVE_PB"
    detail = (
        f"year={chosen['year']}; TE={chosen['te']}; MI={chosen['mi']}; OEI={chosen['oei']}; "
        f"common={chosen['common']}; shares={shares}; raw_close={px}; pb_common={pb}"
    )
    flags.append("PB_NUMERATOR_RAW_CLOSE")
    flags.append("PB_DENOMINATOR_COMMON_BPS")
    return float(pb), chosen["published_at"], mts, flags, detail


def build_fi_peer_observations(
    *,
    subject_instrument_id: str,
    as_of: datetime,
    financial: Sequence[FinancialObservation],
    market: Sequence[MarketObservation],
    classifications: Sequence[InstrumentClassification] | None = None,
    use_lean_curated: bool = False,
    extra_candidates: Sequence[str] | None = None,
    zeros_explicit: bool = True,
    fund_db: Path | str | None = None,
) -> FiPeerUniverseReport:
    """Emit PIT pb_common PeerObservations + exclusion funnel for deposit-taking FI peers."""
    aids = cite(
        "RIM-FI-PEER-UNIVERSE-v2",
        "RIM-COMMON-EQUITY-v1",
        "RIM-PB-ROE-PEER-v1",
        "HITHINK-NO-VENDOR-QFQ-v1",
        "INDUSTRY-SW-L1-PROXY-EM-v1",
    )
    flags: list[str] = list(_UNIVERSE_FLAG_SEED)
    candidates = discover_bank_candidates(
        subject_instrument_id=subject_instrument_id,
        classifications=classifications,
        as_of=as_of,
        use_lean_curated=use_lean_curated,
        extra_candidates=extra_candidates,
        fund_db=fund_db,
    )
    if use_lean_curated:
        flags.append("LEAN_CURATED_CANDIDATES")
    else:
        flags.append("CLASSIFICATIONS_ONLY_CANDIDATES")

    bank_label = deposit_taking_fi_sw_label()
    # Latest PIT classification per instrument — stale non-deposit rows must not veto curated FI names.
    latest_cls_by_id: dict[str, InstrumentClassification] = {}
    for c in classifications or []:
        if c.published_at > as_of:
            continue
        prev = latest_cls_by_id.get(c.instrument_id)
        if prev is None or c.published_at >= prev.published_at:
            latest_cls_by_id[c.instrument_id] = c
    nonbank_by_id: dict[str, str] = {}
    for iid, c in latest_cls_by_id.items():
        if bank_label and c.industry == bank_label:
            continue
        nonbank_by_id[iid] = c.industry

    peers: list[PeerObservation] = []
    excluded: list[PeerExclusionRecord] = []
    peer_diagnostics: list[dict[str, Any]] = []
    funnel: dict[str, int] = {}

    def _bump(reason: str) -> None:
        funnel[reason] = funnel.get(reason, 0) + 1

    for pid in candidates:
        if pid == subject_instrument_id:
            _bump("SELF_PEER")
            excluded.append(PeerExclusionRecord(pid, ["SELF_PEER"]))
            continue
        if pid in nonbank_by_id:
            _bump("NOT_DEPOSIT_TAKING_FI")
            excluded.append(PeerExclusionRecord(
                pid, ["NOT_DEPOSIT_TAKING_FI"], detail=f"industry={nonbank_by_id[pid]}",
            ))
            continue

        pb, pub, mts, cflags, detail = compute_peer_pb_common(
            peer_instrument_id=pid,
            as_of=as_of,
            financial=financial,
            market=market,
            zeros_explicit=zeros_explicit,
        )
        # Peer-level cflags stay on exclusion / peer_diagnostics — never universe flags.
        if pb is None or pub is None or mts is None:
            reason = detail or "PEER_BUILD_FAILED"
            _bump(reason)
            excluded.append(PeerExclusionRecord(
                pid, [reason], detail=detail, peer_flags=list(cflags),
            ))
            peer_diagnostics.append({
                "peer_instrument_id": pid, "included": False, "flags": list(cflags), "reason": reason,
            })
            continue
        # Belt-and-suspenders: compute_peer_pb_common already PIT-filters; keep explicit reject.
        if pub > as_of or mts > as_of:
            _bump("PIT_AFTER_ASOF")
            excluded.append(PeerExclusionRecord(
                pid, ["PIT_AFTER_ASOF"], detail=detail, peer_flags=list(cflags),
            ))
            peer_diagnostics.append({
                "peer_instrument_id": pid, "included": False, "flags": list(cflags),
                "reason": "PIT_AFTER_ASOF",
            })
            continue
        peers.append(
            PeerObservation(
                subject_instrument_id=subject_instrument_id,
                peer_instrument_id=pid,
                published_at=pub,
                field_name=PEER_FIELD_PB_COMMON,
                value=float(pb),
                currency="CNY",
                unit_scale="unit",
                metric_timestamp=mts,
                source_id=SOURCE_ID,
                quality_status=QualityStatus.DERIVED,
                revision_id="pb_common=raw_close/(TE-MI-OEI)/shares;RIM-FI-PEER-UNIVERSE-v2",
            )
        )
        peer_diagnostics.append({
            "peer_instrument_id": pid, "included": True, "flags": list(cflags),
        })
        _bump("INCLUDED")

    if not peers:
        flags.append("FI_PEER_UNIVERSE_EMPTY")
        detail = f"n_candidates={len(candidates)}; funnel={funnel}"
    else:
        detail = f"n_peers={len(peers)}; n_excluded={len(excluded)}; funnel={funnel}"

    return FiPeerUniverseReport(
        subject_instrument_id=subject_instrument_id,
        as_of=as_of.isoformat(),
        peers=peers,
        excluded=excluded,
        candidate_ids=candidates,
        flags=sorted(set(flags)),
        assumption_ids=aids,
        funnel=funnel,
        peer_diagnostics=peer_diagnostics,
        detail=detail,
    )
