"""Exit-multiple cross-check (SPEC §11.3). EXIT-MULTIPLE-SEPARATE-v1."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.schemas.config import ExitMultipleConfig


class ExitMultipleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valid: bool
    invalid_reason: str | None = None
    metric: Literal["ebitda", "ebit"]
    metric_value: float | None
    multiple_used: float | None
    peer_n: int
    peer_median: float | None
    enterprise_value: float | None
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def _robust_multiple(cfg: ExitMultipleConfig) -> tuple[float, float | None, int, list[str]]:
    flags: list[str] = []
    peers = [p for p in cfg.peers if math.isfinite(p) and p > 0]
    if peers:
        med = float(np.median(peers))
        n = len(peers)
        k = cfg.shrink_strength
        mult = (n * med + k * cfg.shrink_prior) / (n + k) if (n + k) > 0 else cfg.shrink_prior
        if n < 3:
            flags.append("PEER_SCARCITY")
        return mult, med, n, flags
    if cfg.multiple is None:
        raise ValueError("exit_multiple requires peers or an explicit multiple")
    flags.append("EXPLICIT_MULTIPLE_NO_PEERS")
    return float(cfg.multiple), None, 0, flags


def exit_multiple_ev(*, metric_value: float, cfg: ExitMultipleConfig) -> ExitMultipleResult:
    assumptions = cite("EXIT-MULTIPLE-SEPARATE-v1")
    if not math.isfinite(metric_value):
        return ExitMultipleResult(valid=False, invalid_reason="NONFINITE_METRIC", metric=cfg.metric,
                                  metric_value=None, multiple_used=None, peer_n=0, peer_median=None,
                                  enterprise_value=None, assumptions=assumptions)
    # Negative normalized earnings: multiple cross-check not economically meaningful
    if metric_value <= 0:
        return ExitMultipleResult(valid=False, invalid_reason="NONPOSITIVE_METRIC", metric=cfg.metric,
                                  metric_value=metric_value, multiple_used=None, peer_n=0, peer_median=None,
                                  enterprise_value=None, flags=["EXIT_MULTIPLE_SKIPPED_NONPOSITIVE_METRIC"],
                                  assumptions=assumptions)
    mult, med, n, flags = _robust_multiple(cfg)
    ev = mult * metric_value
    return ExitMultipleResult(valid=True, metric=cfg.metric, metric_value=metric_value, multiple_used=mult,
                              peer_n=n, peer_median=med, enterprise_value=ev, flags=sorted(flags),
                              assumptions=assumptions)
