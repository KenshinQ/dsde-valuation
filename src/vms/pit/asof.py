"""Decision-timestamp (as_of) parsing.

Versioned assumption ASOF-DATE-CLOSE-1: a date-only as_of means **15:00:00 Asia/Shanghai**
(A-share continuous-auction close) on that date. Announcements published after the close
(typically evenings) are therefore excluded until the next date's as_of. Explicit tz-aware
datetimes are used as given; naive datetimes are rejected.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

AS_OF_DATE_RULE = {
    "id": "ASOF-DATE-CLOSE",
    "version": "1",
    "rule": "date-only as_of => 15:00:00 Asia/Shanghai (market close) on that date",
    "time": "15:00:00",
    "timezone": "Asia/Shanghai",
}
_CLOSE = time(15, 0, 0)
_TZ = ZoneInfo(AS_OF_DATE_RULE["timezone"])


class AsOfError(ValueError):
    pass


def parse_as_of(text: str) -> tuple[datetime, str]:
    """Return (tz-aware datetime, interpretation note)."""
    text = text.strip()
    if len(text) == 10:
        try:
            d = date.fromisoformat(text)
        except ValueError:
            raise AsOfError(f"as_of {text!r} is not a valid YYYY-MM-DD date") from None
        return datetime.combine(d, _CLOSE, _TZ), (
            f"date-only as_of interpreted by {AS_OF_DATE_RULE['id']}-v{AS_OF_DATE_RULE['version']}: "
            f"{AS_OF_DATE_RULE['rule']}")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise AsOfError(f"as_of {text!r} is not ISO-8601; use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS+08:00") from None
    if dt.tzinfo is None:
        raise AsOfError(f"as_of {text!r} is timezone-naive; append an offset such as +08:00")
    return dt, "explicit timezone-aware timestamp"
