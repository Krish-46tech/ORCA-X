"""Small deterministic parser for common relative marine-data date phrases."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone


def resolve_relative_period(query: str, *, today: date | None = None) -> dict[str, str] | None:
    """Resolve common relative periods against latest expected source availability.

    The source delay is explicitly represented: phrases about today end on the
    latest expected available day (UTC today minus three days), not today's date.
    """
    today = today or datetime.now(timezone.utc).date()
    q = re.sub(r"\s+", " ", query.lower())
    latest = today - timedelta(days=3)
    if re.search(r"\b(today|right now|currently)\b", q):
        return {"start": latest.isoformat(), "end": latest.isoformat(),
                "label": "today request; latest expected source day"}
    if re.search(r"\b(last week|previous week)\b", q):
        this_monday = today - timedelta(days=today.weekday())
        start = this_monday - timedelta(days=7)
        return {"start": start.isoformat(), "end": (start + timedelta(days=6)).isoformat(), "label": "previous calendar week"}
    if re.search(r"\b(this week|past week)\b", q):
        start = today - timedelta(days=today.weekday())
        end = min(today, latest)
        if end < start:
            return {"start": end.isoformat(), "end": end.isoformat(),
                    "label": "no observations expected yet this week; latest available source day"}
        return {"start": start.isoformat(), "end": end.isoformat(), "label": "current calendar week through latest expected source day"}
    if re.search(r"\b(last month|previous month)\b", q):
        first_this_month = today.replace(day=1)
        end = first_this_month - timedelta(days=1)
        start = end.replace(day=1)
        return {"start": start.isoformat(), "end": end.isoformat(), "label": "previous calendar month"}
    if re.search(r"\b(this month|month to date)\b", q):
        end = min(today, latest)
        start = today.replace(day=1)
        if end < start:
            start = end
        return {"start": start.isoformat(), "end": end.isoformat(), "label": "current month through latest expected source day"}
    match = re.search(r"\b(?:last|past|over the last)\s+(\d+)\s+days?\b", q)
    if match:
        requested_days = max(1, int(match.group(1)))
        days = min(365, requested_days)
        label = (f"last {requested_days} days requested, capped at the 365-day retrieval limit" if requested_days > 365
                 else f"last {days} days through latest expected source day")
        return {"start": (latest - timedelta(days=days-1)).isoformat(), "end": latest.isoformat(),
                "label": label}
    return None
