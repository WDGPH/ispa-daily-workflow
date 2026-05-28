from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from panorama_compliance.domain.common.workdays import WorkdayInfo

RUN_DATE_FORMAT = "%Y%m%d"
WORKDAYS_DATE_FORMAT = "%Y-%m-%d"


def parse_run_date(value: str | None) -> date:
    if value is None:
        return date.today()
    return datetime.strptime(value, RUN_DATE_FORMAT).date()


def load_workdays(path: Path) -> dict[date, WorkdayInfo]:
    if not path.exists():
        raise FileNotFoundError(f"Workdays file not found: {path}")

    output: dict[date, WorkdayInfo] = {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} is missing a header row")

        for row in reader:
            raw_date = (row.get("Date") or "").strip()
            if not raw_date:
                raise ValueError(f"{path} has empty Date value: {row}")
            day = datetime.strptime(raw_date, WORKDAYS_DATE_FORMAT).date()

            raw_business = (row.get("Business Day") or "").strip().upper()
            if raw_business not in {"TRUE", "FALSE"}:
                raise ValueError(
                    f"{path} invalid Business Day for {raw_date}: {raw_business or 'EMPTY'}"
                )

            raw_prev = (row.get("Previous Business Day") or "").strip()
            previous_business_day = (
                datetime.strptime(raw_prev, WORKDAYS_DATE_FORMAT).date()
                if raw_prev
                else None
            )

            output[day] = WorkdayInfo(
                holiday=(row.get("Holiday") or "").strip(),
                business_day=raw_business == "TRUE",
                previous_business_day=previous_business_day,
            )

    if not output:
        raise ValueError(f"{path} did not contain any workdays")
    return output


def previous_business_day_for(path: Path, run_day: date) -> date | None:
    workdays = load_workdays(path)
    info = workdays.get(run_day)
    if info is None:
        return None
    return info.previous_business_day
