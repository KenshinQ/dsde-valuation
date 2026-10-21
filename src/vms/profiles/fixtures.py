"""Load Phase-2 synthetic profile fixtures from examples/profile_fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vms.profiles.features import ProfileFeatureBundle


class FixtureError(ValueError):
    pass


def fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "examples" / "profile_fixtures"


def load_fixture(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FixtureError(f"fixture not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise FixtureError(f"{path}: invalid JSON: {e}") from None
    if "features" not in data:
        raise FixtureError(f"{path}: missing 'features' object")
    return data


def features_from_fixture(data: dict[str, Any]) -> ProfileFeatureBundle:
    return ProfileFeatureBundle.model_validate(data["features"])


def list_fixtures() -> list[Path]:
    d = fixtures_dir()
    return sorted(d.glob("*.json"))
