from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DATE_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True)
class Holiday:
    name: str
    day: date


def parse_holidays(path: Path) -> list[Holiday]:
    holidays: list[Holiday] = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} is missing a header row")
        for row in reader:
            name = (row.get("Holiday") or "").strip()
            day_str = (row.get("Date") or "").strip()
            if not name or not day_str:
                raise ValueError(f"{path} has an empty Holiday or Date value: {row}")
            try:
                day = datetime.strptime(day_str, DATE_FORMAT).date()
            except ValueError as exc:
                raise ValueError(f"{path} has an invalid date: {day_str}") from exc
            holidays.append(Holiday(name=name, day=day))
    if not holidays:
        raise ValueError(f"{path} did not contain any holidays")
    return holidays


def infer_year(holidays: Sequence[Holiday]) -> int:
    years = {holiday.day.year for holiday in holidays}
    if len(years) != 1:
        raise ValueError(f"Holidays span multiple years: {sorted(years)}")
    return next(iter(years))


def is_business_day(day: date, holiday_lookup: dict[date, str]) -> bool:
    if day.weekday() >= 5:
        return False
    return day not in holiday_lookup


def previous_business_day(day: date, holiday_lookup: dict[date, str]) -> date:
    candidate = day - timedelta(days=1)
    while not is_business_day(candidate, holiday_lookup):
        candidate -= timedelta(days=1)
    return candidate


def date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def build_rows(
    days: Iterable[date],
    holiday_lookup: dict[date, str],
) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for day in days:
        holiday_name = holiday_lookup.get(day, "NA")
        business_day = is_business_day(day, holiday_lookup)
        prev_day = previous_business_day(day, holiday_lookup)
        rows.append(
            (
                day.strftime(DATE_FORMAT),
                holiday_name,
                "TRUE" if business_day else "FALSE",
                prev_day.strftime(DATE_FORMAT),
            )
        )
    return rows


def write_csv(path: Path, rows: Sequence[tuple[str, str, str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "Holiday", "Business Day", "Previous Business Day"])
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a workdays CSV from a holidays CSV."
    )
    parser.add_argument(
        "--holidays",
        type=Path,
        required=True,
        help="Path to the holidays CSV (Holiday,Date).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the workdays CSV.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Override the year inferred from the holidays CSV.",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Override start date (YYYY-MM-DD). Defaults to Feb 1 of the year.",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Override end date (YYYY-MM-DD). Defaults to Jun 30 of the year.",
    )
    args = parser.parse_args()

    holidays = parse_holidays(args.holidays)
    year = args.year if args.year is not None else infer_year(holidays)

    if args.start:
        start_date = datetime.strptime(args.start, DATE_FORMAT).date()
    else:
        start_date = date(year, 2, 1)
    if args.end:
        end_date = datetime.strptime(args.end, DATE_FORMAT).date()
    else:
        end_date = date(year, 6, 30)

    if start_date > end_date:
        raise ValueError("Start date must be on or before end date.")

    holiday_lookup = {holiday.day: holiday.name for holiday in holidays}
    rows = build_rows(date_range(start_date, end_date), holiday_lookup)
    write_csv(args.output, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
