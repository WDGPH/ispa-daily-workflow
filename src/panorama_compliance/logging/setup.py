from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class LongNumericRedactionFilter(logging.Filter):
    def __init__(self, redact_long_numeric_ids: bool = False) -> None:
        super().__init__()
        self.redact_long_numeric_ids = redact_long_numeric_ids

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.redact_long_numeric_ids:
            return True
        message = str(record.getMessage())
        # Preserve YYYYMMDD date tokens while redacting long numeric identifiers.
        message = re.sub(r"\b(?!20\d{6}\b)\d{6,}\b", "[REDACTED_ID]", message)
        record.msg = message
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, tz: tzinfo) -> None:
        super().__init__()
        self._tz = tz

    def format(self, record: logging.LogRecord) -> str:
        created = datetime.fromtimestamp(record.created, tz=self._tz)
        timestamp = created.isoformat(timespec="seconds")
        if created.tzinfo == timezone.utc:
            timestamp = timestamp.replace("+00:00", "Z")
        payload = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


class TimezoneAwareTextFormatter(logging.Formatter):
    def __init__(self, fmt: str, *, datefmt: str, tz: tzinfo) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._tz = tz

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=self._tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="seconds")


TORONTO_STANDARD_OFFSET = timedelta(hours=-5)
TORONTO_DAYLIGHT_OFFSET = timedelta(hours=-4)


def _first_sunday(year: int, month: int) -> int:
    day = datetime(year, month, 1).weekday()
    return 1 + ((6 - day) % 7)


def _second_sunday(year: int, month: int) -> int:
    return _first_sunday(year, month) + 7


def _toronto_offset_for_utc(utc_dt: datetime) -> timedelta:
    if utc_dt.tzinfo is None:
        raise ValueError("Expected a timezone-aware UTC datetime")
    utc = utc_dt.astimezone(timezone.utc)
    year = utc.year
    dst_start_utc = datetime(
        year,
        3,
        _second_sunday(year, 3),
        7,
        0,
        tzinfo=timezone.utc,
    )
    dst_end_utc = datetime(
        year,
        11,
        _first_sunday(year, 11),
        6,
        0,
        tzinfo=timezone.utc,
    )
    if dst_start_utc <= utc < dst_end_utc:
        return TORONTO_DAYLIGHT_OFFSET
    return TORONTO_STANDARD_OFFSET


def _toronto_is_dst(local_dt: datetime) -> bool:
    if local_dt.tzinfo is None:
        raise ValueError("Expected a timezone-aware Toronto datetime")
    local = local_dt.replace(tzinfo=None)
    year = local.year
    dst_start_local = datetime(year, 3, _second_sunday(year, 3), 2, 0)
    dst_end_local = datetime(year, 11, _first_sunday(year, 11), 2, 0)
    ambiguous_start = dst_end_local - timedelta(hours=1)
    if ambiguous_start <= local < dst_end_local:
        return local_dt.fold == 0
    return dst_start_local <= local < dst_end_local


class TorontoFallbackTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        if dt is None:
            return None
        if _toronto_is_dst(dt):
            return TORONTO_DAYLIGHT_OFFSET
        return TORONTO_STANDARD_OFFSET

    def dst(self, dt: datetime | None) -> timedelta | None:
        if dt is None:
            return None
        return timedelta(hours=1) if _toronto_is_dst(dt) else timedelta(0)

    def tzname(self, dt: datetime | None) -> str | None:
        return "America/Toronto"

    def fromutc(self, dt: datetime | None) -> datetime:
        if dt is None:
            raise ValueError("Expected a datetime")
        if dt.tzinfo is not self:
            raise ValueError("Expected a datetime with this tzinfo")
        utc = dt.replace(tzinfo=timezone.utc)
        offset = _toronto_offset_for_utc(utc)
        local = (utc + offset).replace(tzinfo=self)
        year = local.year
        dst_end_local = datetime(year, 11, _first_sunday(year, 11), 2, 0)
        ambiguous_start = dst_end_local - timedelta(hours=1)
        if (
            offset == TORONTO_STANDARD_OFFSET
            and ambiguous_start <= local.replace(tzinfo=None) < dst_end_local
        ):
            local = local.replace(fold=1)
        return local


def _resolve_timezone(value: str | None) -> tzinfo:
    if value is None:
        return datetime.now().astimezone().tzinfo or timezone.utc
    token = str(value).strip()
    if not token:
        return datetime.now().astimezone().tzinfo or timezone.utc
    if token.upper() in {"UTC", "Z"}:
        return timezone.utc
    try:
        return ZoneInfo(token)
    except ZoneInfoNotFoundError:
        if token == "America/Toronto":
            return TorontoFallbackTimezone()
        return datetime.now().astimezone().tzinfo or timezone.utc


def setup_logging(
    log_name: str | None = None,
    *,
    log_dir: Path | None = None,
    level: int = logging.INFO,
    fmt: str = "text",
    redact_long_numeric_ids: bool = False,
    include_sensitive_ids: bool | None = None,
    debug_http: bool = False,
    timezone_name: str | None = None,
) -> Path | None:
    if include_sensitive_ids is not None:
        redact_long_numeric_ids = not bool(include_sensitive_ids)

    tz = _resolve_timezone(timezone_name)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_path: Path | None = None

    if log_name:
        resolved_log_dir = log_dir or Path("logs")
        resolved_log_dir.mkdir(parents=True, exist_ok=True)
        log_path = resolved_log_dir / log_name
        handlers.insert(0, logging.FileHandler(log_path))

    formatter: logging.Formatter
    if fmt == "json":
        formatter = JsonFormatter(tz)
    else:
        formatter = TimezoneAwareTextFormatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            tz=tz,
        )

    redaction_filter = LongNumericRedactionFilter(
        redact_long_numeric_ids=redact_long_numeric_ids
    )
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(redaction_filter)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    http_level = logging.INFO if debug_http else logging.WARNING
    third_party_http_loggers = [
        "httpx",
        "httpcore",
        "azure",
        "azure.core.pipeline",
        "azure.core.pipeline.policies.http_logging_policy",
        "msgraph",
        "microsoft_kiota",
        "kiota",
    ]
    for logger_name in third_party_http_loggers:
        logging.getLogger(logger_name).setLevel(http_level)

    return log_path
