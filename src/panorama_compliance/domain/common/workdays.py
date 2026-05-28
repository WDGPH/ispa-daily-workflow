from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WorkdayInfo:
    holiday: str
    business_day: bool
    previous_business_day: date | None


__all__ = ["WorkdayInfo"]
