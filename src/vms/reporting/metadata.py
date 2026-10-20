"""Run metadata, canonical hashing and artifact writing (SPEC §8.3, §16.3)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
from vms.seeding import BIT_GENERATOR


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace variance, no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def hash_models(models: Iterable[BaseModel]) -> str:
    """Order-independent content hash of a collection of records."""
    rows = sorted(canonical_json(m.model_dump(mode="json")) for m in models)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def code_version() -> dict[str, Any]:
    """Git SHA + dirty flag of the source tree; 'unknown' outside a git checkout."""
    here = Path(__file__).resolve().parent
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=here, capture_output=True,
                             text=True, check=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "src"], cwd=here,
                                    capture_output=True, text=True, check=True,
                                    timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        sha, dirty = "unknown", None
    return {"package_version": __version__, "git_sha": sha, "src_dirty": dirty}


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    schema_version: str = SCHEMA_VERSION
    implemented_phase: str = IMPLEMENTED_PHASE
    seed: int = Field(ge=0)
    bit_generator: str = BIT_GENERATOR
    monte_carlo_paths: int = Field(gt=0)
    data_hash: str
    config_hash: str
    request_hash: str
    code_version: dict[str, Any]


def make_run_metadata(*, request: BaseModel, config_snapshot: dict, data_hash: str,
                      seed: int, paths: int) -> RunMetadata:
    """run_id is content-addressed: identical request/config/data/code ⇒ identical run_id.

    Wall-clock time is deliberately excluded from deterministic artifacts so that
    reproducibility can be checked by hashing; it is written to run_context.json.
    """
    config_hash = sha256_of(config_snapshot)
    request_hash = sha256_of(request.model_dump(mode="json"))
    cv = code_version()
    run_key = sha256_of({"request": request_hash, "config": config_hash, "data": data_hash,
                         "code": cv["git_sha"], "schema": SCHEMA_VERSION})
    return RunMetadata(run_id=f"vms-{run_key[:16]}", seed=seed, monte_carlo_paths=paths,
                       data_hash=data_hash, config_hash=config_hash, request_hash=request_hash,
                       code_version=cv)


def write_artifact(out_dir: Path, name: str, payload: dict, meta: RunMetadata) -> Path:
    """Write one JSON artifact stamped with run_id and schema_version."""
    body = {"run_id": meta.run_id, "schema_version": meta.schema_version, **payload}
    path = Path(out_dir) / name
    path.write_text(json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")
    return path
