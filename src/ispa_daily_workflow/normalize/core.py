from __future__ import annotations

import math
import numbers
import re
from datetime import date, datetime, timedelta

import polars as pl

from ispa_daily_workflow.reference import SchoolReference

EXCEL_DATE_EPOCH = date(1899, 12, 30)
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m/%d/%y",
    "%d/%m/%y",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
)


def normalize_text(value: object, uppercase: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = re.sub(r"\s+", " ", str(value).strip())
    return text.upper() if uppercase else text


def normalize_school_name(value: object) -> str:
    return normalize_text(value, uppercase=True).replace("&", "AND")


def is_missing(value: object) -> bool:
    if value is None:
        return True
    return bool(isinstance(value, float) and math.isnan(value))


def parse_date_value(value: object) -> date | None:
    if is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        try:
            serial = int(float(value))
            return EXCEL_DATE_EPOCH + timedelta(days=serial)
        except (OverflowError, TypeError, ValueError):
            return None

    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        if len(raw) == 8:
            try:
                return datetime.strptime(raw, "%Y%m%d").date()
            except ValueError:
                pass
        try:
            return EXCEL_DATE_EPOCH + timedelta(days=int(raw))
        except (OverflowError, ValueError):
            pass

    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        pass

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_year_value(value: object) -> int | None:
    parsed = parse_date_value(value)
    return parsed.year if parsed else None


def parse_school_name_and_id(
    raw_name: object, raw_id: object
) -> tuple[str, str | None]:
    school_name = normalize_school_name(raw_name)
    school_id: str | None = None

    if (
        school_name
        and " - " in school_name
        and (raw_id is None or str(raw_id).strip() == "")
    ):
        name_part, id_part = school_name.rsplit(" - ", 1)
        digits = re.sub(r"\D", "", id_part)
        if digits:
            school_id = digits
            school_name = name_part.strip()

    if raw_id is not None and str(raw_id).strip() != "":
        digits = re.sub(r"\D", "", str(raw_id))
        if digits:
            school_id = digits

    return school_name, school_id


def _normalize_id_expr(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.replace(r"\.0$", "")
        .str.replace_all(r"\s+", "")
        .alias(column)
    )


def _clean_school_id_expr(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Utf8, strict=False)
        .fill_null("")
        .str.replace(r"\.0$", "")
        .str.replace_all(r"\D", "")
        .map_elements(lambda value: value if value else None, return_dtype=pl.Utf8)
        .alias(column)
    )


def _school_label_expr() -> pl.Expr:
    return (
        pl.when(pl.col("school_name").is_not_null() & pl.col("school_id").is_not_null())
        .then(
            pl.concat_str([pl.col("school_name"), pl.lit(" - "), pl.col("school_id")])
        )
        .when(pl.col("school_name").is_not_null())
        .then(pl.col("school_name"))
        .otherwise(pl.col("school_id"))
        .alias("school_label")
    )


def _reference_record_for_row(
    school_id: str | None,
    school_name: str | None,
    reference: SchoolReference,
) -> tuple[str | None, str | None, str | None]:
    record = None
    if school_id and school_id in reference.by_id:
        record = reference.by_id[school_id]
    elif school_name and school_name in reference.by_name:
        record = reference.by_name[school_name]
    if record is None:
        return None, None, None
    return record.level, record.wave, record.fq_group


def normalize_compliance_dataframe(
    df: pl.DataFrame,
    *,
    reference: SchoolReference | None = None,
    source_file: str | None = None,
    wave: str | None = None,
) -> pl.DataFrame:
    transformed = df

    if "client_id" in transformed.columns:
        transformed = transformed.with_columns(_normalize_id_expr("client_id"))
    if "ontario_immunization_id" in transformed.columns:
        transformed = transformed.with_columns(
            _normalize_id_expr("ontario_immunization_id")
        )
    if "school_id" in transformed.columns:
        transformed = transformed.with_columns(_clean_school_id_expr("school_id"))

    uppercase_text_columns = [
        "first_name",
        "last_name",
        "middle_name",
        "school_name",
    ]
    for column in uppercase_text_columns:
        if column in transformed.columns:
            transformed = transformed.with_columns(
                pl.col(column)
                .cast(pl.Utf8, strict=False)
                .fill_null("")
                .str.strip_chars()
                .str.replace_all(r"\s+", " ")
                .str.to_uppercase()
                .alias(column)
            )

    if "school_name" in transformed.columns:
        transformed = transformed.with_columns(
            pl.col("school_name").str.replace_all("&", "AND").alias("school_name")
        )

    passthrough_text_columns = [
        "grade",
        "class",
        "gender",
        "school_board",
        "primary_phone",
        "street_address",
        "city",
        "province",
        "postal_code",
        "guardian_1_first_name",
        "guardian_1_last_name",
        "guardian_1_phone",
        "guardian_2_first_name",
        "guardian_2_last_name",
        "guardian_2_phone",
        "reported_diseases_agents",
        "immunization_history_by_agent",
        "immunization_history_by_disease",
        "meningococcal_disease_status",
    ]
    for column in passthrough_text_columns:
        if column in transformed.columns:
            transformed = transformed.with_columns(
                pl.col(column)
                .cast(pl.Utf8, strict=False)
                .str.strip_chars()
                .alias(column)
            )

    for column in ("date_of_birth", "compliant"):
        if column in transformed.columns:
            transformed = transformed.with_columns(
                pl.col(column)
                .map_elements(parse_date_value, return_dtype=pl.Date)
                .alias(column)
            )

    if "school_label" not in transformed.columns and (
        "school_name" in transformed.columns or "school_id" in transformed.columns
    ):
        if "school_name" not in transformed.columns:
            transformed = transformed.with_columns(
                pl.lit(None, dtype=pl.Utf8).alias("school_name")
            )
        if "school_id" not in transformed.columns:
            transformed = transformed.with_columns(
                pl.lit(None, dtype=pl.Utf8).alias("school_id")
            )
        transformed = transformed.with_columns(_school_label_expr())

    if source_file is not None and "source_file" not in transformed.columns:
        transformed = transformed.with_columns(pl.lit(source_file).alias("source_file"))

    if wave is not None and "wave" not in transformed.columns:
        transformed = transformed.with_columns(pl.lit(wave).alias("wave"))

    if reference is not None and {"school_id", "school_name"}.issubset(
        set(transformed.columns)
    ):
        lookup = transformed.select(["school_id", "school_name"]).to_dicts()
        levels: list[str | None] = []
        waves: list[str | None] = []
        fq_groups: list[str | None] = []
        for row in lookup:
            level, ref_wave, fq_group = _reference_record_for_row(
                row.get("school_id"),
                row.get("school_name"),
                reference,
            )
            levels.append(level)
            waves.append(ref_wave)
            fq_groups.append(fq_group)
        transformed = transformed.with_columns(
            pl.Series("school_level", levels, dtype=pl.Utf8),
            pl.Series("suspension_wave", waves, dtype=pl.Utf8),
            pl.Series("fq_group", fq_groups, dtype=pl.Utf8),
        )

    return transformed


def sort_students(df: pl.DataFrame) -> pl.DataFrame:
    columns = [name for name in ["last_name", "first_name"] if name in df.columns]
    if not columns:
        return df
    return df.sort(columns)
