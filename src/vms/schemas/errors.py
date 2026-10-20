"""Turn pydantic ValidationErrors into short, actionable messages."""

from __future__ import annotations

from pydantic import ValidationError


def format_validation_error(err: ValidationError, context: str = "") -> str:
    lines = []
    prefix = f"{context}: " if context else ""
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "<root>"
        msg = e["msg"].removeprefix("Value error, ")
        inp = e.get("input")
        shown = "" if isinstance(inp, dict) else f" (got {inp!r})"
        lines.append(f"{prefix}{loc}: {msg}{shown}")
    return "\n".join(lines)
