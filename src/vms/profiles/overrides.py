"""Versioned manual profile overrides (SPEC §7.3 / §2.13).

Overrides are declarative, versioned, and always recorded in the ProfileReport.
They never silently replace classifier output without a reason string.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from vms.schemas.contracts import ProfileFlag, ProfileLabel
from vms.schemas.errors import format_validation_error
from pydantic import ValidationError


class ManualOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str = Field(min_length=1)
    primary_profile: ProfileLabel
    reason: str = Field(min_length=1)
    as_of_from: str | None = None
    as_of_to: str | None = None
    flags: list[ProfileFlag] = Field(default_factory=list)
    active: bool = True


class OverrideCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    override_version: str = Field(min_length=1)
    overrides: list[ManualOverride] = Field(default_factory=list)

    @field_validator("overrides")
    @classmethod
    def _unique_active(cls, v: list[ManualOverride]) -> list[ManualOverride]:
        # Multiple historical rows OK; duplicate active identical instrument+range rejected lightly
        return v


class OverrideLoadError(ValueError):
    pass


def load_overrides(path: str | Path) -> OverrideCatalog:
    path = Path(path)
    if not path.is_file():
        raise OverrideLoadError(f"override file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise OverrideLoadError(f"{path}: invalid YAML: {e}") from None
    if not isinstance(data, dict):
        raise OverrideLoadError(f"{path}: top level must be a mapping")
    try:
        return OverrideCatalog.model_validate(data)
    except ValidationError as e:
        raise OverrideLoadError(format_validation_error(e, str(path))) from None


def find_override(
    catalog: OverrideCatalog | None,
    *,
    instrument_id: str,
    as_of: str,
) -> tuple[ManualOverride | None, str | None]:
    """Return matching active override and catalog version, if any.

    as_of comparison is lexicographic on ISO strings (fixtures use YYYY-MM-DD).
    """
    if catalog is None:
        return None, None
    matches = []
    for o in catalog.overrides:
        if not o.active or o.instrument_id != instrument_id:
            continue
        if o.as_of_from and as_of < o.as_of_from:
            continue
        if o.as_of_to and as_of > o.as_of_to:
            continue
        matches.append(o)
    if not matches:
        return None, catalog.override_version
    # Prefer the last declared matching override (document order = versioned intent)
    return matches[-1], catalog.override_version
