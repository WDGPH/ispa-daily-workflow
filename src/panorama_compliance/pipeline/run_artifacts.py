from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def stage_summary(
    *,
    status: str,
    started_at: datetime,
    ended_at: datetime,
    **details: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "started_at": iso_utc(started_at),
        "ended_at": iso_utc(ended_at),
    }
    payload.update(details)
    return payload


def daily_run_id(run_date: str) -> str:
    return f"{utc_now().strftime('%Y%m%dT%H%M%SZ')}_daily_{run_date}"
