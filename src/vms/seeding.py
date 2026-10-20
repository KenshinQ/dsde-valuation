"""Deterministic seeding (SPEC §8.3).

All randomness must come from a ``numpy.random.Generator`` derived from the
request seed. Named sub-streams are derived via ``SeedSequence`` with a stable
(hash-based, not Python-``hash()``-based) key, so adding a new stream never
shifts the numbers drawn by existing streams.
"""

from __future__ import annotations

import hashlib

import numpy as np

BIT_GENERATOR = "PCG64"


def _check_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise TypeError(f"seed must be a non-negative integer, got {type(seed).__name__}")
    if seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    return int(seed)


def make_rng(seed: int) -> np.random.Generator:
    """Root generator for a seed."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(_check_seed(seed))))


def _stream_key(name: str) -> int:
    if not name:
        raise ValueError("stream name must be non-empty")
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "little")


def stream_rng(seed: int, name: str) -> np.random.Generator:
    """Independent, named sub-stream (e.g. 'synthetic_data', 'driver_paths')."""
    ss = np.random.SeedSequence(entropy=_check_seed(seed), spawn_key=(_stream_key(name),))
    return np.random.Generator(np.random.PCG64(ss))
