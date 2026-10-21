"""Asset-based NAV (SPEC §12.7).

Book balance values are NOT automatically fair values. Each material asset and
claim needs an explicit fair-value assumption (and optional haircut) with a
non-empty justification. Missing asset-level inputs ⇒ data-gap / unsupported —
never a fabricated complete NAV from raw book totals alone.
"""

from __future__ import annotations

import math
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms.assumptions import cite

INVALID_NAV_REASONS = (
    "MISSING_ASSET_INPUTS",
    "BOOK_AS_FAIR_UNJUSTIFIED",
    "NONFINITE_NAV",
    "EMPTY_ASSET_SCHEDULE",
    "CLAIM_WITHOUT_BASIS",
)


class NavLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    line_id: str = Field(min_length=1)
    kind: Literal["asset", "claim"]
    book_value: float | None = None
    fair_value: float | None = None
    haircut: float = Field(default=0.0, ge=0.0, le=1.0)
    justification: str = ""
    basis: str = Field(
        default="",
        description="appraisal | market | yield | replacement | reserve | impairment | configured",
    )

    @model_validator(mode="after")
    def _finite(self) -> "NavLine":
        for name in ("book_value", "fair_value", "haircut"):
            v = getattr(self, name)
            if v is not None and not math.isfinite(float(v)):
                raise ValueError(f"{name} must be finite")
        return self


class NavResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    invalid_reason: str | None = None
    unsupported: bool = False
    data_gap: list[str] = Field(default_factory=list)
    nav_equity: float | None = None
    gross_asset_fair: float | None = None
    gross_claim_fair: float | None = None
    lines: list[dict[str, Any]] = Field(default_factory=list)
    reconciliation: dict[str, Any] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    detail: str = ""


def _effective_fair(line: NavLine) -> tuple[float | None, list[str], list[str]]:
    """Return (value_after_haircut, flags, gaps)."""
    flags: list[str] = []
    gaps: list[str] = []
    if line.fair_value is None:
        gaps.append(f"{line.line_id}:missing_fair_value")
        return None, flags, gaps
    if not line.justification.strip():
        # Fair value without justification is not acceptable (book≠fair by default)
        if line.book_value is not None and math.isclose(line.fair_value, line.book_value, rel_tol=0, abs_tol=1e-9):
            gaps.append(f"{line.line_id}:book_as_fair_unjustified")
            flags.append("BOOK_AS_FAIR_UNJUSTIFIED")
            return None, flags, gaps
        gaps.append(f"{line.line_id}:missing_justification")
        return None, flags, gaps
    if line.book_value is not None and math.isclose(line.fair_value, line.book_value, rel_tol=0, abs_tol=1e-9):
        if "book" in line.justification.lower() and len(line.justification.strip()) < 12:
            # Too-thin "use book" justification
            flags.append("THIN_BOOK_FAIR_JUSTIFICATION")
        flags.append("FAIR_EQUALS_BOOK_EXPLICIT")
    fv = float(line.fair_value) * (1.0 - float(line.haircut))
    if line.haircut > 0:
        flags.append(f"HAIRCUT_{line.line_id}")
    return fv, flags, gaps


def compute_nav(
    *,
    assets: Sequence[NavLine | dict[str, Any]],
    claims: Sequence[NavLine | dict[str, Any]] = (),
    allow_book_totals_only: bool = False,
    corporate_overhead_pv: float = 0.0,
    disposal_tax: float = 0.0,
    diluted_shares: float | None = None,
) -> NavResult:
    """Compute NAV from explicit asset/claim fair-value lines.

    ``allow_book_totals_only`` is always treated as False for production semantics;
    the parameter exists only so callers cannot accidentally opt into book=fair.
    """
    assumptions = cite("NAV-EXPLICIT-FAIR-v1", "NAV-BOOK-NE-FAIR-v1")
    flags: list[str] = []
    if allow_book_totals_only:
        # Hard refuse — book totals alone never produce a complete NAV
        return NavResult(
            valid=False,
            invalid_reason="MISSING_ASSET_INPUTS",
            unsupported=True,
            data_gap=["book_totals_only_forbidden"],
            flags=["BOOK_TOTALS_ONLY_FORBIDDEN"],
            assumptions=assumptions,
            detail="raw book assets/liabilities cannot produce NAV without explicit fair-value lines",
        )

    def _coerce(rows: Sequence[NavLine | dict[str, Any]], kind: str) -> list[NavLine]:
        out: list[NavLine] = []
        for r in rows:
            if isinstance(r, NavLine):
                out.append(r if r.kind == kind else r.model_copy(update={"kind": kind}))  # type: ignore[arg-type]
            else:
                data = dict(r)
                data.setdefault("kind", kind)
                out.append(NavLine(**data))
        return out

    asset_lines = _coerce(assets, "asset")
    claim_lines = _coerce(claims, "claim")
    if not asset_lines:
        return NavResult(
            valid=False,
            invalid_reason="EMPTY_ASSET_SCHEDULE",
            unsupported=True,
            data_gap=["assets"],
            assumptions=assumptions,
            detail="NAV requires a non-empty asset schedule with fair-value assumptions",
        )

    line_rows: list[dict[str, Any]] = []
    gaps: list[str] = []
    asset_sum = 0.0
    claim_sum = 0.0
    for line in asset_lines:
        fv, fl, g = _effective_fair(line)
        flags.extend(fl)
        gaps.extend(g)
        line_rows.append({
            "line_id": line.line_id, "kind": "asset",
            "book_value": line.book_value, "fair_value": line.fair_value,
            "haircut": line.haircut, "effective_fair": fv,
            "justification": line.justification, "basis": line.basis,
            "gaps": g,
        })
        if fv is not None:
            asset_sum += fv
    for line in claim_lines:
        fv, fl, g = _effective_fair(line)
        flags.extend(fl)
        gaps.extend(g)
        line_rows.append({
            "line_id": line.line_id, "kind": "claim",
            "book_value": line.book_value, "fair_value": line.fair_value,
            "haircut": line.haircut, "effective_fair": fv,
            "justification": line.justification, "basis": line.basis,
            "gaps": g,
        })
        if fv is not None:
            claim_sum += fv

    if gaps:
        reason = "BOOK_AS_FAIR_UNJUSTIFIED" if any("book_as_fair" in g for g in gaps) else "MISSING_ASSET_INPUTS"
        return NavResult(
            valid=False,
            invalid_reason=reason,
            unsupported=True,
            data_gap=sorted(set(gaps)),
            lines=line_rows,
            flags=sorted(set(flags)),
            assumptions=assumptions,
            detail=f"NAV data-gap: {gaps}",
        )

    overhead = float(corporate_overhead_pv or 0.0)
    tax = float(disposal_tax or 0.0)
    nav = asset_sum - claim_sum - overhead - tax
    if not math.isfinite(nav):
        return NavResult(
            valid=False, invalid_reason="NONFINITE_NAV", unsupported=True,
            data_gap=["nonfinite"], assumptions=assumptions, flags=flags,
        )
    recon = {
        "gross_asset_fair_after_haircut": asset_sum,
        "gross_claim_fair_after_haircut": claim_sum,
        "corporate_overhead_pv": overhead,
        "disposal_tax": tax,
        "nav_equity": nav,
        "n_assets": len(asset_lines),
        "n_claims": len(claim_lines),
        "value_per_share": (nav / diluted_shares) if diluted_shares and diluted_shares > 0 else None,
    }
    return NavResult(
        valid=True,
        invalid_reason=None,
        unsupported=False,
        data_gap=[],
        nav_equity=nav,
        gross_asset_fair=asset_sum,
        gross_claim_fair=claim_sum,
        lines=line_rows,
        reconciliation=recon,
        flags=sorted(set(flags)),
        assumptions=assumptions,
        detail=f"NAV equity={nav:.4f} from {len(asset_lines)} assets / {len(claim_lines)} claims",
    )


def book_totals_are_not_nav(
    *,
    total_assets: float | None,
    total_liabilities: float | None,
) -> NavResult:
    """Explicit refusal when only book totals are supplied."""
    return NavResult(
        valid=False,
        invalid_reason="MISSING_ASSET_INPUTS",
        unsupported=True,
        data_gap=["asset_fair_value_schedule", "claim_fair_value_schedule"],
        reconciliation={
            "book_total_assets": total_assets,
            "book_total_liabilities": total_liabilities,
            "book_equity_implied": (
                None if total_assets is None or total_liabilities is None
                else float(total_assets) - float(total_liabilities)
            ),
            "note": "book equity is NOT NAV; fair-value schedule required",
        },
        flags=["BOOK_NE_FAIR", "APPARENTLY_COMPLETE_NAV_FORBIDDEN"],
        assumptions=cite("NAV-EXPLICIT-FAIR-v1", "NAV-BOOK-NE-FAIR-v1"),
        detail="refusing to equate raw book assets/liabilities with NAV",
    )
