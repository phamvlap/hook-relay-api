from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def parse_retry_after(
    header_value: str | None,
    now: datetime | None = None,
) -> float | None:
    """Parse an RFC 9110 Retry-After header into delay in seconds.

    Supports:
    - Integer / Float delta-seconds: "120" -> 120.0
    - IMF-fixdate / RFC 2822 date: "Wed, 21 Oct 2026 07:28:00 GMT" -> delta seconds

    Returns None if header is missing, blank, or invalid.
    """
    if not header_value:
        return None

    cleaned = header_value.strip()
    if not cleaned:
        return None

    # 1. Try parsing as delta-seconds
    try:
        seconds = float(cleaned)
        return max(0.0, seconds)
    except (ValueError, TypeError):
        pass

    # 2. Try parsing as HTTP-Date
    try:
        target_date = parsedate_to_datetime(cleaned)
        current_time = now or datetime.now(tz=UTC)
        if target_date.tzinfo is None:
            target_date = target_date.replace(tzinfo=UTC)

        delta = (target_date - current_time).total_seconds()
        return max(0.0, delta)
    except (TypeError, ValueError, OverflowError):
        return None
